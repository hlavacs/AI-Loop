import * as vscode from "vscode";
import { BackendClient } from "./backendClient";
import { BackendError, CreatedProject, TargetOperationResult } from "./protocol";
import { ProjectSession } from "./projectSession";
import { EvidenceTrees } from "./evidenceTrees";
import { SpecificationView } from "./specificationView";
import { WorkflowView } from "./workflowView";
import { ProposalView } from "./proposalView";
import { ProposalReview } from "./proposalData";
import { ProjectTree } from "./projectTree";
import { projectTreeData, ProjectTreeNode, TargetSelection } from "./projectTreeData";
import { resolveBackend, resolvePython } from "./pythonRuntime";
import { sameContext } from "./sessionState";
import { revealSource, sourceWarning, watchSourceSaves } from "./sourceEditor";
import { entityChoices } from "./sourceNavigation";
import { CallViewPanel } from "./callViewPanel";
import { registerTraceCommands } from "./callViewMessages";
import { viewError } from "./viewErrors";
import { FileViewPanel } from "./fileViewPanel";
import { registerFileCommands } from "./fileViewMessages";
import { MindMapPanel } from "./mindMapPanel";
import { registerMindMapCommand } from "./mindMapMessages";
import { ClassViewPanel } from "./classViewPanel";
import { registerClassCommand } from "./classViewMessages";
import { projectFile } from "./sourceChanges";
import { formatToolchain, toolchainParams, ToolchainInspection } from "./toolchain";

import { registerTargetCommands, runTargetOperation } from "./targetOperations";

let active: ExtensionController | undefined;

/** Activation registers UI only; Python starts on an explicit backend command. */
export function activate(context: vscode.ExtensionContext): IntegrationTestApi | undefined {
  active = new ExtensionController(context.extensionUri);
  context.subscriptions.push({ dispose: () => { void deactivate(); } });
  return context.extensionMode === vscode.ExtensionMode.Test ? active.integrationHooks() : undefined;
}

export async function deactivate(): Promise<void> {
  const controller = active;
  active = undefined;
  await controller?.dispose();
}

class ExtensionController {
  private readonly output = vscode.window.createOutputChannel("ICODA");
  private readonly tree = new ProjectTree();
  private readonly view: vscode.TreeView<ProjectTreeNode>;
  private readonly listeners: vscode.Disposable[] = [];
  private readonly session = new ProjectSession(message => this.output.appendLine(message), () => this.refresh());
  private readonly evidence: EvidenceTrees;
  private readonly specification: SpecificationView;
  private readonly workflows: WorkflowView;
  private readonly proposals: ProposalView;
  private client?: BackendClient;
  private starting?: Promise<BackendClient>;
  private busy = 0;
  private changingSelection = false;
  private disposal?: Promise<void>;
  private saveListener?: vscode.Disposable;
  private watchedSession?: string;
  private callView?: CallViewPanel;
  private proposalCallView?: CallViewPanel;
  private fileView?: FileViewPanel;
  private classView?: ClassViewPanel;
  private mindMap?: MindMapPanel;
  private projectFolder?: string;
  private reopen?: { root: string; targetId: string | null };

  /** Read-only observations and UI seams, exported only by a test-mode activation. */
  integrationHooks() {
    return {
      snapshot: () => structuredClone({ backendStarted: Boolean(this.client), project: this.session.data,
        model: this.session.model, tree: this.tree.getChildren(), treeMessage: this.view.message }),
      callView: () => this.callView?.integrationHooks(),
      proposalCallView: () => this.proposalCallView?.integrationHooks(),
      fileView: () => this.fileView?.integrationHooks(),
      classView: () => this.classView?.integrationHooks(),
      mindMap: () => this.mindMap?.integrationHooks(),
    };
  }

  constructor(private readonly extensionUri: vscode.Uri) {
    this.view = vscode.window.createTreeView("icoda.project", {
      treeDataProvider: this.tree,
    });
    this.evidence = new EvidenceTrees(this.session, () => this.backend(), message => this.output.appendLine(message));
    this.specification = new SpecificationView(this.session, () => this.backend(), async action => {
      if (this.disposal || this.busy || this.changingSelection) {
        throw new BackendError("operation_busy", "Wait for the current ICODA operation before saving the specification.");
      }
      this.busy++;
      try { await action(); } finally { this.busy--; }
    });
    this.proposals = new ProposalView(this.session, () => this.backend(), () => this.workflows.continueAfterApproval(),
      () => this.proposalCallView?.dispose());
    this.workflows = new WorkflowView(this.session, () => this.backend(),
      () => !this.busy && !this.changingSelection && !this.client?.busy && this.session.data?.modelState === "fresh",
      () => this.proposals.refresh());
    this.registerCommands();
    this.listeners.push(
      vscode.workspace.onDidChangeWorkspaceFolders(event => {
        if (event.removed.some(folder => folder.uri.toString() === this.projectFolder)) void this.closeWorkspace();
        else this.refresh();
      }),
      vscode.workspace.onDidGrantWorkspaceTrust(() => this.refresh()),
      vscode.workspace.onDidChangeConfiguration(event => {
        if (event.affectsConfiguration("icoda.pythonPath")) {
          this.output.appendLine("Python setting changed. Run ICODA: Restart Backend to apply it.");
        }
      }),
    );
    this.refresh();
  }

  private registerCommands(): void {
    this.listeners.push(
      ...registerTraceCommands((name, action) => vscode.commands.registerCommand(name, action),
        async action => { await this.callView?.traceCommand(action); }),
      registerMindMapCommand((name, action) => vscode.commands.registerCommand(name, action),
        () => this.run(() => this.showMindMap())),
      registerClassCommand((name, action) => vscode.commands.registerCommand(name, action),
        () => this.run(() => this.showClassView())),
      ...registerFileCommands((name, action) => vscode.commands.registerCommand(name, action),
        () => this.run(() => this.showFileView()), () => this.run(() => this.revealInFileView()),
        () => this.run(async () => { if (await this.revealInFileView()) await this.fileView?.assignSelected(); })),
      ...registerTargetCommands((name, action) => vscode.commands.registerCommand(name, action),
        (method, title) => this.run(() => this.targetOperation(method, title))),
      vscode.commands.registerCommand("icoda.openProject", () => this.run(() => this.openProject(), true)),
      vscode.commands.registerCommand("icoda.newProject", () => this.run(() => this.newProject())),
      vscode.commands.registerCommand("icoda.analyseProject", () => this.run(() => this.analyseProject())),
      vscode.commands.registerCommand("icoda.selectTarget", (selection?: TargetSelection) =>
        this.run(() => this.selectTarget(selection), true)),
      vscode.commands.registerCommand("icoda.revealEntity", () => this.run(() => this.revealEntity())),
      vscode.commands.registerCommand("icoda.showCallView", () => this.run(() => this.showCallView())),
      vscode.commands.registerCommand("icoda.showProposalCallView", () => this.run(() => this.showProposalCallView())),
      vscode.commands.registerCommand("icoda.showOutput", () => this.output.show(true)),
      vscode.commands.registerCommand("icoda.showToolchain", () => this.run(() => this.showToolchain())),
      vscode.commands.registerCommand("icoda.restartBackend", () => this.run(() => this.restartBackend(), true)),
    );
  }

  private async run(action: () => Promise<unknown>, supersede = false): Promise<void> {
    if (this.disposal) return;
    if (this.changingSelection || (this.busy && !supersede)) {
      void vscode.window.showInformationMessage("An ICODA project operation is running. Please wait.");
      return;
    }
    this.busy++;
    if (supersede) this.changingSelection = true;
    try {
      await action();
    } catch (error) {
      if (!this.disposal) this.reportError(error);
    } finally {
      this.busy--;
      if (supersede) this.changingSelection = false;
    }
  }

  private reportError(error: unknown): void {
    const message = viewError(error);
    this.output.appendLine(String(error));
    if (error instanceof BackendError && error.code === "cancelled") {
      void vscode.window.showInformationMessage("ICODA: Operation cancelled or superseded.");
    } else if (error instanceof BackendError && ["stale_revision", "invalid_session", "stale_target"].includes(error.code)) {
      void vscode.window.showWarningMessage(`ICODA: ${message} Refresh the project to continue.`, "Refresh Project")
        .then(choice => { if (choice && !this.disposal) void vscode.commands.executeCommand("icoda.openProject"); });
    } else {
      void vscode.window.showErrorMessage(`ICODA: ${message}`);
    }
  }

  private async newProject(): Promise<void> {
    if (!vscode.workspace.isTrusted) throw new BackendError("not_trusted", "Trust this workspace before creating a project.");
    const ticket = this.session.identity.capture();
    const current = () => !this.disposal && vscode.workspace.isTrusted && this.session.identity.isCurrent(ticket);
    try {
      const folders = await vscode.window.showOpenDialog({ canSelectFiles: false, canSelectFolders: true,
        canSelectMany: false, title: "New ICODA Project: Choose Parent Folder", openLabel: "Choose Parent Folder" });
      if (!current() || !folders?.length) return;
      const parent = folders[0]!;
      if (parent.scheme !== "file") throw new BackendError("invalid_params", "Choose a local parent folder.");
      const nameProblem = (value: string) => !value.trim() || value.includes("\0") ? "Enter a project name." : undefined;
      const name = await vscode.window.showInputBox({ title: "New ICODA Project: Name",
        prompt: "Name of the new folder and specification title. Existing folders are preserved.",
        ignoreFocusOut: true, validateInput: nameProblem });
      if (!current() || name === undefined) return;
      if (nameProblem(name)) throw new BackendError("invalid_params", nameProblem(name)!);
      const language = await vscode.window.showQuickPick(["C++", "Python"], { title: "New ICODA Project: Language",
        placeHolder: "Use the shared default Code Profile and skeleton", ignoreFocusOut: true });
      if (!current() || language === undefined) return;
      if (language !== "C++" && language !== "Python") throw new BackendError("invalid_params", "Choose C++ or Python.");
      const summary = await vscode.window.showInputBox({ title: "New ICODA Project: Description",
        prompt: "Optional specification description. Edit the full specification after opening the project.",
        ignoreFocusOut: true });
      if (!current() || summary === undefined) return;
      const client = await this.backend();
      if (!current()) return;
      const created = await client.request<CreatedProject>("project.create", {
        parentPath: parent.fsPath, name, language, summary, trusted: vscode.workspace.isTrusted,
      }, ticket.context);
      if (!current()) return;
      this.output.appendLine(`Created ${created.root}: ${created.writtenFiles.length} skeleton files; architecture phase.`);
      const choice = await vscode.window.showInformationMessage(
        `Created ICODA project at ${created.root}. Open it to edit the specification, build or analyse.`,
        "Open in New Window", "Add to Workspace");
      if (!current()) return;
      const uri = vscode.Uri.file(created.root);
      if (choice === "Open in New Window") await vscode.commands.executeCommand("vscode.openFolder", uri, true);
      else if (choice === "Add to Workspace"
          && !vscode.workspace.updateWorkspaceFolders(vscode.workspace.workspaceFolders?.length ?? 0, 0, { uri })) {
        throw new Error(`Project created at ${created.root}, but VS Code could not add it to the workspace.`);
      }
    } catch (error) {
      if (current()) throw error;
      this.output.appendLine("Dropped obsolete new-project result.");
    }
  }

  private async openProject(): Promise<boolean> {
    const folder = await chooseFolder();
    if (!folder || this.disposal) return false;
    const client = await this.backend();
    if (this.disposal) return false;
    this.output.show(true);
    this.projectFolder = folder.uri.toString();
    await this.saveViewStates();
    this.closePanels();
    return this.session.open(client, folder.uri.fsPath);
  }

  private async analyseProject(automatic = false): Promise<void> {
    if (!this.session.identity.context && !await this.openProject()) return;
    const client = await this.backend();
    if (this.disposal) return;
    await this.saveViewStates();
    await vscode.window.withProgress({
      location: automatic ? vscode.ProgressLocation.Window : vscode.ProgressLocation.Notification,
      title: `ICODA: Analysing ${this.session.data?.root}`, cancellable: true,
    }, async (progress, token) => {
      const controller = new AbortController();
      const listener = token.onCancellationRequested(() => controller.abort());
      if (token.isCancellationRequested) controller.abort();
      try { await this.session.analyse(client, { signal: controller.signal, progress: message => progress.report({ message }) },
        automatic ? { automatic: true, unsavedDocuments: this.unsavedDocuments() } : {}); }
      finally { listener.dispose(); }
    });
  }

  private async selectTarget(selection?: TargetSelection): Promise<void> {
    const context = this.session.identity.context;
    if (!context) throw new BackendError("project_not_open", "Open a project first.");
    const client = await this.backend();
    if (!selection) {
      const items = this.session.data!.targets.map(target => ({
        label: target.label, description: target.id === context.targetId ? "selected" : target.kind,
        detail: target.configuration ?? undefined, picked: target.id === context.targetId, targetId: target.id,
      }));
      const item = await vscode.window.showQuickPick(items, { placeHolder: "Choose the ICODA executable, library or Whole Project" });
      if (!item) return;
      selection = { context, targetId: item.targetId };
    }
    if (this.disposal) return;
    if (!sameContext(selection.context, this.session.identity.context)) {
      throw new BackendError("stale_revision", "This target item belongs to an older project selection.");
    }
    await this.saveViewStates();
    await this.session.select(client, selection.targetId);
  }

  private async revealEntity(): Promise<void> {
    const { data, model, sourceRootId } = this.session;
    if (!data || !model || !sourceRootId || !vscode.workspace.isTrusted) return;
    const ticket = this.session.identity.capture();
    const items = entityChoices(model, data.root, sourceRootId);
    if (!items.length) {
      sourceWarning(message => this.output.appendLine(message), "No analysed source locations. Run ICODA: Analyse Project.");
      return;
    }
    const item = await vscode.window.showQuickPick(items, {
      placeHolder: "Go to an ICODA file, class or function", matchOnDescription: true, matchOnDetail: true,
    });
    if (!item || this.disposal || !this.session.identity.isCurrent(ticket)) return;
    const client = await this.backend();
    if (this.disposal || !this.session.identity.isCurrent(ticket)) return;
    await revealSource({ client, session: this.session, log: message => this.output.appendLine(message) }, item.ref, false);
  }

  private async showCallView(): Promise<void> {
    const ticket = this.session.identity.capture();
    if (!ticket.context) throw new BackendError("project_not_open", "Open a project first.");
    const client = await this.backend();
    if (this.disposal || !this.session.identity.isCurrent(ticket)) return;
    if (this.callView) { this.callView.reveal(); return; }
    this.callView = new CallViewPanel(this.extensionUri, {
      client, session: this.session, log: message => this.output.appendLine(message),
    }, () => { this.callView = undefined; });
  }

  private async targetOperation(method: string, title: string): Promise<void> {
    const client = await this.backend(); // Enforce trust even for programmatic command invocation.
    const ticket = this.session.identity.capture();
    if (!ticket.context || this.disposal) throw new BackendError("project_not_open", "Open a project first.");
    const scope = this.projectFolder ? vscode.Uri.parse(this.projectFolder) : undefined;
    const config = vscode.workspace.getConfiguration("icoda", scope);
    this.output.show(true);
    const result = await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification, title: `ICODA: ${title}`, cancellable: true,
    }, (progress, token) => runTargetOperation(client, this.session, method,
      { ...toolchainParams(key => config.get(key, "")), trusted: vscode.workspace.isTrusted },
      token, message => progress.report({ message })));
    if (!result || this.disposal) return;
    if (method === "trace.record") await this.offerRecording(result);
  }

  private async showProposalCallView(): Promise<void> {
    const client = await this.backend(), ticket = this.session.identity.capture();
    if (!ticket.context || this.disposal) return;
    const review = await client.request<ProposalReview>("proposal.get", {
      unsavedDocuments: vscode.workspace.textDocuments.filter(document => document.isDirty).map(document => document.uri.toString()),
    }, ticket.context);
    if (this.disposal || !this.session.identity.accept(ticket, review, "read") || !vscode.workspace.isTrusted) return;
    this.proposalCallView?.dispose();
    if (!review.candidateGraph) {
      void vscode.window.showInformationMessage("ICODA: No current candidate graph. Review or rebuild a code proposal first.");
      return;
    }
    this.proposalCallView = new CallViewPanel(this.extensionUri, {
      client, session: this.session, log: message => this.output.appendLine(message),
      candidateSource: { ...ticket.context, ...review.candidateGraph },
    }, () => { this.proposalCallView = undefined; });
  }

  private async showFileView(): Promise<void> {
    const ticket = this.session.identity.capture();
    if (!ticket.context) throw new BackendError("project_not_open", "Open a project first.");
    const client = await this.backend();
    if (this.disposal || !this.session.identity.isCurrent(ticket)) return;
    if (this.fileView) { this.fileView.reveal(); return; }
    this.fileView = new FileViewPanel(this.extensionUri, {
      client, session: this.session, log: message => this.output.appendLine(message),
    }, () => { this.fileView = undefined; }, () => { void this.run(() => this.revealInFileView()); });
  }

  private async revealInFileView(): Promise<boolean> {
    const { data, sourceRootId } = this.session;
    if (!data || !sourceRootId || !vscode.workspace.isTrusted) return false;
    const editor = vscode.window.activeTextEditor
      ?? (vscode.window.visibleTextEditors.length === 1 ? vscode.window.visibleTextEditors[0] : undefined);
    const file = editor?.document.uri.scheme === "file" ? projectFile(data.root, editor.document.uri.fsPath) : undefined;
    const ref = this.callView?.selectedSource() ?? (file ? { sourceRootId, file } : undefined);
    if (!ref) { sourceWarning(message => this.output.appendLine(message), "Select a project file or Call View function first."); return false; }
    await this.showFileView();
    try { await this.fileView?.revealFile(ref); return true; }
    catch (error) { sourceWarning(message => this.output.appendLine(message), viewError(error)); return false; }
  }

  private async showClassView(): Promise<void> {
    const ticket = this.session.identity.capture();
    if (!ticket.context) throw new BackendError("project_not_open", "Open a project first.");
    const client = await this.backend();
    if (this.disposal || !this.session.identity.isCurrent(ticket)) return;
    if (this.classView) { this.classView.reveal(); return; }
    this.classView = new ClassViewPanel(this.extensionUri, {
      client, session: this.session, log: message => this.output.appendLine(message),
    }, () => { this.classView = undefined; });
  }

  private async showMindMap(): Promise<void> {
    const ticket = this.session.identity.capture();
    if (!ticket.context) throw new BackendError("project_not_open", "Open a project first.");
    const client = await this.backend();
    if (this.disposal || !this.session.identity.isCurrent(ticket)) return;
    if (this.mindMap) { this.mindMap.reveal(); return; }
    this.mindMap = new MindMapPanel(this.extensionUri, {
      client, session: this.session, log: message => this.output.appendLine(message),
    }, () => { this.mindMap = undefined; });
  }

  private async offerRecording(result: TargetOperationResult): Promise<void> {
    this.output.appendLine(`Recording: ${result.path}\nExecutable: ${result.executable}\nTarget: ${result.target.label}`);
    const choice = await vscode.window.showInformationMessage(
      `ICODA: Recorded ${result.target.label}. ${result.path}`, "Load Trace");
    if (!choice || !result.path || this.disposal || !sameContext(result, this.session.identity.context)) return;
    await this.showCallView();
    await this.callView?.loadRecording(result);
  }

  private backend(): Promise<BackendClient> {
    if (this.disposal) return Promise.reject(new BackendError("backend_disposed", "ICODA is closing."));
    if (!vscode.workspace.isTrusted) {
      return Promise.reject(new Error("Trust this workspace before starting the ICODA Python backend."));
    }
    this.starting ??= this.startBackend().catch(error => {
      this.starting = undefined;
      throw error;
    });
    return this.starting;
  }

  private async showToolchain(): Promise<void> {
    const client = await this.backend();
    if (this.disposal) return;
    const scope = this.projectFolder ? vscode.Uri.parse(this.projectFolder) : undefined;
    const config = vscode.workspace.getConfiguration("icoda", scope);
    this.output.show(true);
    const report = await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification, title: "ICODA: Inspecting toolchain", cancellable: false,
    }, () => client.request<ToolchainInspection>("toolchain.inspect", toolchainParams(key => config.get(key, ""))));
    if (!this.disposal) this.output.appendLine(formatToolchain(report));
  }

  private async startBackend(): Promise<BackendClient> {
    await this.client?.dispose();
    const configured = vscode.workspace.getConfiguration("icoda").get<string>("pythonPath", "");
    const packageRoot = await resolveBackend(this.extensionUri.fsPath);
    const python = await resolvePython(packageRoot, configured);
    if (this.disposal) throw new Error("ICODA is deactivating.");
    this.output.appendLine(`Starting Python: ${python}\nBackend package root: ${packageRoot}`);
    const client = new BackendClient({
      python, packageRoot,
      log: text => this.output.append(text),
      onNotification: message => {
        if (message.method === "operation.log" && typeof message.params.message === "string"
            && (!["sessionId", "modelRevision", "targetId"].some(key => key in message.params)
            || (message.params.sessionId === this.session.identity.context?.sessionId
            && message.params.modelRevision === this.session.identity.context?.modelRevision
            && message.params.targetId === this.session.identity.context?.targetId))) {
          this.output.append(message.params.message);
        }
      },
      onExit: error => this.backendExited(client, error),
      onRequest: method => this.workflows.activity(method),
    });
    this.client = client;
    this.refresh();
    const initialized = await client.ready;
    this.output.appendLine(`Effective Python: ${initialized.runtime.python}`);
    this.output.appendLine(`Backend ${initialized.backendVersion}; protocol ${initialized.protocolVersion}`);
    this.refresh();
    return client;
  }

  private backendExited(client: BackendClient, error: Error): void {
    if (this.client !== client) return;
    this.output.appendLine(error.message);
    this.starting = undefined;
    this.session.reset();
    // Keep the client until close, so restart/deactivation can await process cleanup.
    void client.closed.then(() => {
      if (this.client === client) {
        this.client = undefined;
        if (!this.disposal) this.refresh();
      }
    });
  }

  private async restartBackend(): Promise<void> {
    const reopen = this.reopen;
    await this.saveViewStates();
    this.closePanels();
    this.session.reset();
    await this.client?.dispose();
    this.client = undefined;
    this.starting = undefined;
    this.session.reset();
    if (this.disposal) return;
    this.refresh();
    const client = await this.backend();
    if (reopen && !this.disposal && await this.session.open(client, reopen.root)) {
      if (this.session.data?.targets.some(target => target.id === reopen.targetId)) await this.session.select(client, reopen.targetId);
    }
    this.output.appendLine("Backend restarted; the previous project selection was restored when available.");
  }

  private refresh(): void {
    if (this.disposal) return;
    const context = this.session.identity.context;
    if (context && this.session.data) this.reopen = { root: this.session.data.root, targetId: context.targetId };
    this.watchProject(context?.sessionId);
    this.callView?.sync();
    this.proposalCallView?.sync();
    this.fileView?.sync();
    this.classView?.sync();
    this.mindMap?.sync();
    this.evidence.sync();
    this.specification.sync();
    this.workflows.sync();
    this.proposals.sync();
    const data = projectTreeData({
      hasFolder: Boolean(vscode.workspace.workspaceFolders?.length), trusted: vscode.workspace.isTrusted,
      backendStarted: Boolean(this.client), project: this.session.data, context,
    });
    this.view.message = data.message;
    this.tree.update(data.items);
    void vscode.commands.executeCommand("setContext", "icoda.projectOpen", Boolean(context));
  }

  private watchProject(sessionId?: string): void {
    if (sessionId === this.watchedSession) return;
    this.saveListener?.dispose();
    this.saveListener = undefined;
    this.watchedSession = sessionId;
    if (sessionId) this.saveListener = watchSourceSaves(this.session, message => this.output.appendLine(message),
      () => this.automaticAnalysis());
  }

  private unsavedDocuments(): string[] {
    return vscode.workspace.textDocuments.filter(document => document.isDirty).map(document => document.uri.toString());
  }

  private async automaticAnalysis(): Promise<boolean> {
    if (this.disposal || !vscode.workspace.isTrusted || !this.session.data) return true;
    if (!vscode.workspace.getConfiguration("icoda", vscode.Uri.file(this.session.data.root)).get("autoAnalyse", true)) return true;
    if (this.busy || this.changingSelection || this.unsavedDocuments().some(uri => {
      const document = vscode.Uri.parse(uri);
      return document.scheme !== "file" || projectFile(this.session.data!.root, document.fsPath);
    })) return false;
    this.busy++;
    try { await this.analyseProject(true); return true; }
    catch (error) {
      if (error instanceof BackendError && ["workflow_busy", "proposal_pending", "unsaved_documents"].includes(error.code)) return false;
      throw error;
    } finally { this.busy--; }
  }

  dispose(): Promise<void> {
    this.disposal ??= Promise.resolve().then(() => this.close());
    return this.disposal;
  }

  private async saveViewStates(): Promise<void> {
    await Promise.all([this.fileView?.saveState(), this.callView?.saveState(),
      this.classView?.saveState(), this.mindMap?.saveState()]);
  }

  private closePanels(): void {
    this.callView?.dispose();
    this.proposalCallView?.dispose();
    this.fileView?.dispose();
    this.classView?.dispose();
    this.mindMap?.dispose();
    this.callView = undefined; this.fileView = undefined;
    this.classView = undefined; this.mindMap = undefined;
  }

  private async closeWorkspace(): Promise<void> {
    await this.dispose();
    if (active === this) active = new ExtensionController(this.extensionUri);
  }

  private async close(): Promise<void> {
    this.proposals.dispose();
    this.workflows.dispose();
    this.saveListener?.dispose();
    await this.saveViewStates();
    this.closePanels();
    this.evidence.dispose();
    this.specification.dispose();
    this.session.reset();
    void vscode.commands.executeCommand("setContext", "icoda.projectOpen", false);
    for (const listener of this.listeners) listener.dispose();
    this.view.dispose();
    this.tree.dispose();
    await this.client?.dispose();
    this.output.dispose();
  }
}

export type IntegrationTestApi = ReturnType<ExtensionController["integrationHooks"]>;

async function chooseFolder(): Promise<vscode.WorkspaceFolder | undefined> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (!folders.length) {
    void vscode.window.showInformationMessage("Open a workspace folder before using ICODA: Open Project.");
    return undefined;
  }
  const folder = folders.length === 1 ? folders[0] : await vscode.window.showWorkspaceFolderPick({
    placeHolder: "Choose the workspace folder to open in ICODA",
  });
  if (folder && folder.uri.scheme !== "file") {
    throw new Error("ICODA currently requires a workspace folder on the local filesystem.");
  }
  return folder;
}
