import * as vscode from "vscode";
import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError, SessionContext } from "./protocol";
import { candidateDiff, CandidateSelection, ProposalNode, proposalNodes, RecoverySelection, registerProposalCommands, ReviewInput } from "./proposalData";
import { ProposalModel } from "./proposalModel";
import { sameContext } from "./sessionState";

export class ProposalView implements vscode.TreeDataProvider<ProposalNode>, vscode.Disposable {
  private readonly changes = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changes.event;
  private readonly output = vscode.window.createOutputChannel("ICODA Proposal Review");
  private readonly model: ProposalModel;
  private readonly disposables: vscode.Disposable[];
  private disposed = false;
  private recoveryContext?: SessionContext;

  constructor(private readonly session: ProjectSession, backend: () => Promise<BackendClient>,
    private readonly afterApproval: () => void = () => {}, private readonly candidateChanged: () => void = () => {}) {
    const client: Pick<BackendClient, "request"> = { request: async (method, params, context) => (await backend()).request(method, params, context) };
    this.model = new ProposalModel(session, client, () => this.changes.fire(), message => this.output.appendLine(message),
      undefined, () => vscode.workspace.isTrusted);
    this.disposables = [vscode.window.createTreeView("icoda.proposals", { treeDataProvider: this }),
      vscode.workspace.registerTextDocumentContentProvider("icoda-empty", { provideTextDocumentContent: () => "" }),
      ...registerProposalCommands((name, action) => vscode.commands.registerCommand(name, action),
        method => this.execute(method), selection => this.diff(selection), selection => this.recover(selection))];
  }

  sync(): void {
    this.model.sync();
    const context = this.session.identity.context;
    if (!context) { this.recoveryContext = undefined; return; }
    if (this.disposed || !vscode.workspace.isTrusted || sameContext(context, this.recoveryContext)) return;
    this.recoveryContext = context;
    void this.model.loadRecoveries().catch(error => {
      if (!this.disposed && vscode.workspace.isTrusted && sameContext(context, this.session.identity.context)) this.output.appendLine(String(error));
    });
  }
  getChildren(node?: ProposalNode): ProposalNode[] { return node ? [] : proposalNodes(this.model.snapshot, this.model.recoveries); }
  getTreeItem(node: ProposalNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.label);
    item.id = node.id; item.description = node.description;
    item.tooltip = node.description ? `${node.label}\n${node.description}` : node.label;
    if (node.selection) item.command = { command: "icoda.openProposalDiff", title: "Review candidate diff", arguments: [node.selection] };
    if (node.recovery) item.command = { command: "icoda.recoverProposal", title: "Recover interrupted proposal", arguments: [node.recovery] };
    return item;
  }

  refresh(): void { this.recoveryContext = undefined; this.sync(); void this.execute("proposal.get"); }
  private unsaved(): string[] { return vscode.workspace.textDocuments.filter(document => document.isDirty).map(document => document.uri.toString()); }

  private trusted(): boolean {
    if (vscode.workspace.isTrusted) return true;
    void vscode.window.showWarningMessage("ICODA: Proposal decisions need a trusted workspace. Trust this workspace to continue.");
    return false;
  }

  private async recover(selection?: RecoverySelection): Promise<void> {
    if (this.disposed || !this.trusted()) return;
    const ticket = this.session.identity.capture();
    if (!ticket.context || (selection && !sameContext(selection, ticket.context))) return;
    try {
      const retained = await this.model.loadRecoveries();
      if (!retained || !this.model.current(ticket) || !this.trusted()) return;
      const item = selection ? retained.items.find(item => item.id === selection.recoveryId) : retained.items[0];
      if (!item) { void vscode.window.showInformationMessage("ICODA: No interrupted proposal is available."); return; }
      const choice = await vscode.window.showQuickPick(item.choices, { placeHolder: "Recover interrupted proposal" });
      if (!choice || !item.choices.some(option => option.value === choice.value) || !this.model.current(ticket) || !this.trusted()) return;
      const confirmed = choice.value === "discard" && await vscode.window.showWarningMessage(
        "Discard the retained proposal and its candidate edits?", { modal: true, detail: item.worktreeRoot }, "Discard") === "Discard";
      if ((choice.value === "discard" && !confirmed) || !this.model.current(ticket) || !this.trusted()) return;
      const selected = { ...ticket.context, recoveryId: item.id };
      const changed = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
        title: "ICODA: Recovering proposal", cancellable: choice.value === "resume" }, async (progress, token) => {
        const listener = token.onCancellationRequested(() => { void this.model.cancel(); });
        try { return await this.model.recover(selected, choice.value, this.unsaved(), confirmed, message => progress.report({ message })); }
        finally { listener.dispose(); }
      });
      if (!changed || !this.model.current(ticket) || !this.trusted()) return;
      this.candidateChanged();
      await this.model.load(this.unsaved());
      if (!this.model.current(ticket) || !this.trusted()) return;
      if (choice.value === "resume") {
        const file = proposalNodes(this.model.snapshot).find(node => node.selection)?.selection;
        if (file) await this.diff(file);
        this.output.show(true);
      }
    } catch (error) {
      if (this.model.current(ticket) && this.trusted()) {
        this.output.appendLine(String(error));
        void vscode.window.showErrorMessage(`ICODA recovery: ${String(error)}`);
      }
    }
  }

  private async execute(method: string): Promise<void> {
    if (this.disposed || !this.trusted()) return;
    const ticket = this.session.identity.capture();
    if (!ticket.context) { void vscode.window.showInformationMessage("ICODA: Open a project before reviewing proposals."); return; }
    try {
      if (method === "proposal.get" || !this.model.snapshot) await this.model.load(this.unsaved());
      if (!this.model.current(ticket) || !this.trusted()) return;
      this.output.show(true);
      if (method === "proposal.get") return;
      if (method === "history.list") { await this.model.history(); return; }
      const evidence = this.model.snapshot?.evidenceFingerprint;
      const input = await this.input(method);
      if (!input || !this.model.current(ticket) || !this.trusted()) return;
      input.unsavedDocuments = this.unsaved();
      const changed = await this.decide(method, input, evidence);
      if (changed) this.candidateChanged();
      if (changed && !this.disposed && this.session.identity.context?.sessionId === ticket.context.sessionId) {
        await this.model.load(this.unsaved());
        if (method === "proposal.approve" && !this.disposed && vscode.workspace.isTrusted) this.afterApproval();
      }
    } catch (error) {
      if (this.model.current(ticket)) {
        this.output.appendLine(String(error));
        void vscode.window.showErrorMessage(`ICODA: ${String(error)}. See ICODA Proposal Review output.`);
      }
    }
  }

  private async decide(method: string, input: ReviewInput, evidence: string | undefined): Promise<boolean> {
    const ticket = this.session.identity.capture();
    try { return await this.checkDecision(method, input, evidence); }
    catch (error) {
      if (method !== "proposal.approve" || !(error instanceof BackendError) || error.code !== "signature_unconfirmed"
        || input.confirmSignatures || !this.model.current(ticket)) throw error;
      if (!this.trusted() || !await this.confirmSignatures()) return false;
      if (!this.model.current(ticket) || !this.trusted()) return false;
      return this.checkDecision(method, { ...input, confirmSignatures: true, unsavedDocuments: this.unsaved() }, evidence);
    }
  }

  private async checkDecision(method: string, input: ReviewInput, evidence: string | undefined): Promise<boolean> {
    return vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
      title: "ICODA: Checking proposal decision", cancellable: ["proposal.adapt", "proposal.rebuild"].includes(method) }, async (progress, token) => {
      const listener = token.onCancellationRequested(() => { void this.model.cancel(); });
      try { return await this.model.mutate(method, input, message => progress.report({ message }), evidence); }
      finally { listener.dispose(); }
    });
  }

  private async confirmSignatures(): Promise<boolean> {
    const changes = this.model.snapshot?.proposal?.signatureChanges ?? [];
    const detail = changes.map(change => `${change.display_name}\n${change.previous_signature}\n→ ${change.proposed_signature}`).join("\n\n");
    const choice = await vscode.window.showWarningMessage("Confirm the reviewed API signature changes?", { modal: true, detail }, "Confirm signatures");
    return choice === "Confirm signatures";
  }

  private async input(method: string): Promise<ReviewInput | undefined> {
    const input: ReviewInput = { unsavedDocuments: [] }, proposal = this.model.snapshot?.proposal;
    if (method === "proposal.approve") {
      if (!proposal?.canApprove) throw new BackendError("proposal_gate_failed", "Approval is blocked. Inspect the gates and rebuild changed candidates.");
      if (proposal.signatureChanges.length) {
        if (!await this.confirmSignatures()) return undefined;
        input.confirmSignatures = true;
      }
    } else if (method === "proposal.reject") {
      const reason = await vscode.window.showInputBox({ prompt: "Why reject this proposal? The reason is recorded for the next prompt.", validateInput: text => text.trim() ? undefined : "Enter a reason." });
      if (!reason?.trim()) return undefined;
      input.reason = reason;
    } else if (method === "proposal.adapt") return this.adaptationInput();
    else if (method.startsWith("step.")) {
      const message = method === "step.undo" ? "Undo the last approved step with a new revert commit? The core checks its undo conditions." : "Record the saved project edits as a manual step and commit them?";
      if (!await vscode.window.showWarningMessage(message, { modal: true }, "Continue")) return undefined;
    }
    return input;
  }

  private async adaptationInput(): Promise<ReviewInput | undefined> {
    const summary = this.model.snapshot?.proposal?.entitySummary;
    const choice = summary ? await vscode.window.showQuickPick(["Add constraints", "Edit entity summary"], { placeHolder: "Adapt this proposal" }) : "Add constraints";
    if (!choice) return undefined;
    const text = await vscode.window.showInputBox({ prompt: choice === "Edit entity summary" ? "Edit the structured entity JSON. The core validates it." : "Hard constraints for the next attempt, separated by ';'.",
      value: choice === "Edit entity summary" ? JSON.stringify(JSON.parse(summary!)) : "" });
    if (text === undefined) return undefined;
    return { unsavedDocuments: [], ...(choice === "Edit entity summary" ? { entitySummary: text } : { constraints: text.split(";").map(part => part.trim()).filter(Boolean) }) };
  }

  private async diff(selection: CandidateSelection): Promise<void> {
    if (this.disposed || !this.trusted()) return;
    const review = this.model.snapshot;
    if (!review || !sameContext(selection, this.session.identity.context) || selection.evidenceFingerprint !== review.evidenceFingerprint) return;
    try {
      const paths = candidateDiff(review, selection.path);
      const uri = (path: string | null) => path ? vscode.Uri.file(path) : vscode.Uri.parse(`icoda-empty:/${encodeURIComponent(selection.path)}`);
      await vscode.commands.executeCommand("vscode.diff", uri(paths.original), uri(paths.candidate), `ICODA: ${selection.path} (proposal)`, { preview: true });
    } catch (error) { if (!this.disposed) void vscode.window.showErrorMessage(`ICODA source: ${String(error)}`); }
  }

  dispose(): void {
    this.disposed = true; this.model.dispose(); this.changes.dispose(); this.output.dispose();
    for (const disposable of this.disposables) disposable.dispose();
  }
}
