import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError, SessionContext } from "./protocol";
import { DecisionResult, ProposalReview, RecoveryChoice, RecoveryList, RecoverySelection, ReviewInput, StepRecord, validRecoverySelection, validReviewInput } from "./proposalData";
import { sameContext, SessionTicket } from "./sessionState";
import { WorkflowStatus } from "./workflowData";

/** Review tokens are never silently refreshed on a decision; stale editors/files must return to review. */
export class ProposalModel {
  snapshot?: ProposalReview;
  recoveries?: RecoveryList;
  private disposed = false;
  private sequence = 0;
  private recoverySequence = 0;
  private active?: { ticket: SessionTicket; id?: string; cancelled: boolean };

  constructor(readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly changed: () => void, private readonly output: (message: string) => void,
    private readonly pause: () => Promise<void> = () => new Promise(resolve => setTimeout(resolve, 200)),
    private readonly trusted: () => boolean = () => true) {}

  sync(): void {
    if (this.snapshot && !sameContext(this.snapshot, this.session.identity.context)) { this.snapshot = undefined; this.changed(); }
    if (this.recoveries && !sameContext(this.recoveries, this.session.identity.context)) { this.recoveries = undefined; this.changed(); }
  }
  current(ticket: SessionTicket): boolean { return !this.disposed && this.session.identity.isCurrent(ticket); }

  async loadRecoveries(): Promise<RecoveryList | undefined> {
    if (!this.trusted()) return undefined;
    const sequence = ++this.recoverySequence, ticket = this.session.identity.capture();
    const result = await this.read<RecoveryList>("recovery.list", { trusted: true }, ticket);
    if (result && this.trusted() && sequence === this.recoverySequence) {
      this.recoveries = result; this.changed(); return result;
    }
    return undefined;
  }

  async recover(selection: RecoverySelection, choice: RecoveryChoice, unsavedDocuments: string[],
    confirmDiscard: boolean, progress: (message: string) => void = () => {}): Promise<boolean> {
    const ticket = this.session.identity.capture();
    if (!this.current(ticket) || !this.trusted() || !sameContext(selection, ticket.context)) return false;
    if (!validRecoverySelection(selection) || !["resume", "keep", "discard"].includes(choice)
      || typeof confirmDiscard !== "boolean" || !validReviewInput("proposal.rebuild", { unsavedDocuments })) {
      throw new BackendError("invalid_params", "Invalid recovery arguments.");
    }
    if (!this.recoveries || !sameContext(this.recoveries, ticket.context)
      || !this.recoveries.items.some(item => item.id === selection.recoveryId && item.choices.some(option => option.value === choice))) {
      throw new BackendError("recovery_missing", "Refresh interrupted proposals before deciding.");
    }
    if (choice === "discard" && !confirmDiscard) return false;
    if (this.active) throw new BackendError("workflow_busy", "A proposal decision is already running.");
    const active: { ticket: SessionTicket; id?: string; cancelled: boolean } = { ticket, cancelled: false };
    this.active = active;
    try {
      const result = await this.client.request<RecoveryList | WorkflowStatus>("recovery.resolve",
        { recoveryId: selection.recoveryId, choice, unsavedDocuments, confirmDiscard, trusted: this.trusted() }, ticket.context);
      if ("workflow" in result && sameContext(result, ticket.context)) {
        active.id = result.workflow?.id;
        if (active.cancelled) await this.cancel();
      }
      if (!this.current(ticket) || !this.trusted() || !this.session.identity.accept(ticket, result, "read")) return false;
      if ("workflow" in result) {
        this.recoveries = undefined; this.changed();
        return await this.wait(result, ticket, progress);
      }
      this.recoveries = result; this.changed(); return true;
    } catch (error) { if (!this.current(ticket) || !this.trusted()) return false; throw error; }
    finally { if (this.active === active) this.active = undefined; }
  }

  async load(unsavedDocuments: string[]): Promise<ProposalReview | undefined> {
    const sequence = ++this.sequence, ticket = this.session.identity.capture();
    const result = await this.read<ProposalReview>("proposal.get", { unsavedDocuments }, ticket);
    if (result && sequence === this.sequence) { this.snapshot = result; this.changed(); this.showOutputs(result); return result; }
    return undefined;
  }

  async history(): Promise<void> {
    const result = await this.read<SessionContext & { records: StepRecord[] }>("history.list", {}, this.session.identity.capture());
    if (result) for (const record of result.records) this.output(`Step ${record.number}: ${record.decision} — ${record.title}\n${record.reason || record.rationale}\n${record.build_output}\n${record.test_output}`);
  }

  async mutate(method: string, input: ReviewInput, progress: (message: string) => void = () => {},
    evidenceFingerprint = this.snapshot?.evidenceFingerprint): Promise<boolean> {
    if (!validReviewInput(method, input)) throw new BackendError("invalid_params", "Invalid proposal decision arguments.");
    const ticket = this.session.identity.capture(), review = this.snapshot;
    if (!ticket.context || !review || !sameContext(review, ticket.context)) throw new BackendError("stale_evidence", "Review Proposal before deciding.");
    if (review.evidenceFingerprint !== evidenceFingerprint) throw new BackendError("stale_evidence", "The reviewed proposal changed during the decision. Review it again.");
    if (!this.current(ticket)) return false;
    if (this.active) throw new BackendError("workflow_busy", "A proposal decision is already running.");
    if (method === "proposal.approve" && !review.proposal?.canApprove) throw new BackendError("proposal_gate_failed", "Approval is blocked. Review the gate output and rebuild changed candidates.");
    const active: { ticket: SessionTicket; id?: string; cancelled: boolean } = { ticket, cancelled: false };
    this.active = active;
    try {
      const result = await this.client.request<DecisionResult | WorkflowStatus>(method,
        { ...input, evidenceFingerprint: review.evidenceFingerprint, trusted: true }, ticket.context);
      if ("workflow" in result && sameContext(result, ticket.context)) {
        active.id = result.workflow?.id;
        if (active.cancelled) await this.cancel();
      }
      if (!this.current(ticket)) return false;
      if ("workflow" in result) return await this.wait(result, ticket, progress);
      if (!this.session.acceptDecision(ticket, result)) return false;
      this.snapshot = undefined; this.changed();
      this.output(`${result.record?.decision ?? "No changes"}: ${result.record?.commit ?? ""}\n${result.record?.build_output ?? ""}\n${result.record?.test_output ?? ""}`);
      return true;
    } catch (error) { if (!this.current(ticket)) return false; throw error; }
    finally { if (this.active === active) this.active = undefined; }
  }

  private async wait(initial: WorkflowStatus, ticket: SessionTicket, progress: (message: string) => void): Promise<boolean> {
    let result: WorkflowStatus | undefined = initial;
    if (!this.session.identity.accept(ticket, initial, "read")) return false;
    while (result?.workflow?.state === "running" && this.current(ticket) && this.trusted()) {
      progress(result.workflow.message); await this.pause();
      if (!this.trusted()) return false;
      result = await this.read<WorkflowStatus>("workflow.status", { trusted: true, workflowId: result.workflow.id }, ticket);
    }
    if (!result || !this.current(ticket) || !this.trusted()) return false;
    if (result.workflow?.error) this.output(`${result.workflow.error.code}: ${result.workflow.error.message}`);
    this.snapshot = undefined; this.changed();
    return true;
  }

  async cancel(): Promise<void> {
    const active = this.active;
    if (!active) return;
    active.cancelled = true;
    if (active.id && this.session.identity.isCurrent(active.ticket)) {
      try { await this.client.request("workflow.cancel", { trusted: true, workflowId: active.id }, active.ticket.context); }
      catch (error) { if (this.current(active.ticket)) this.output(String(error)); }
    }
  }

  private async read<T extends SessionContext>(method: string, params: object, ticket: SessionTicket): Promise<T | undefined> {
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return undefined;
    try {
      const result = await this.client.request<T>(method, params, ticket.context);
      return this.current(ticket) && this.trusted() && this.session.identity.accept(ticket, result, "read") ? result : undefined;
    } catch (error) { if (this.current(ticket) && this.trusted()) throw error; return undefined; }
  }

  private showOutputs(review: ProposalReview): void {
    const proposal = review.proposal;
    if (proposal) this.output(`Step ${proposal.number}: ${proposal.summary}\n${proposal.delta}\n${proposal.error}\nBuild:\n${proposal.build?.output ?? "Not applicable"}\nTests:\n${proposal.tests?.output ?? "Not applicable"}`);
  }
  dispose(): void { void this.cancel(); this.disposed = true; this.sequence++; this.recoverySequence++; this.snapshot = undefined; this.recoveries = undefined; }
}
