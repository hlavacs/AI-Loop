import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError, SessionContext } from "./protocol";
import { DecisionResult, ProposalReview } from "./proposalData";
import { sameContext, SessionTicket } from "./sessionState";
import { CLICommand, ConversationHistory, QueuePatch, WorkflowInput, WorkflowKind, WorkflowStatus, validQueuePatch, validWorkflowInput } from "./workflowData";

interface CancellationToken {
  readonly isCancellationRequested: boolean;
  onCancellationRequested(listener: () => void): { dispose(): void };
}
interface ActiveWorkflow { ticket: SessionTicket; id?: string; cancelled: boolean; abort?: AbortController }

/** Provider jobs retain their originating session; all late successes and failures are discarded. */
export class WorkflowModel {
  snapshot?: WorkflowStatus;
  private active?: ActiveWorkflow;
  private disposed = false;

  constructor(private readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly changed: () => void, private readonly diagnostic: (message: string) => void,
    private readonly pause: () => Promise<void> = () => new Promise(resolve => setTimeout(resolve, 200)),
    private readonly trusted: () => boolean = () => true,
    private readonly unsaved?: () => string[]) {}

  get busy(): boolean { return Boolean(this.active); }

  async purposeReady(ticket = this.session.identity.capture()): Promise<boolean> {
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return false;
    const result = await this.request<SessionContext & { ready: boolean }>("purpose.status",
      { trusted: true, idle: true, unsavedDocuments: this.unsaved?.() ?? [] }, ticket);
    return result?.ready === true;
  }

  async history(ticket = this.session.identity.capture()): Promise<ConversationHistory | undefined> {
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return undefined;
    return this.request<ConversationHistory>("conversation.history", { trusted: true }, ticket);
  }

  async cli(input: WorkflowInput, ticket = this.session.identity.capture()): Promise<CLICommand | undefined> {
    if (!validWorkflowInput(input) || input.message !== undefined || input.focus !== undefined || input.request !== undefined
      || input.idle !== undefined) throw new BackendError("invalid_params", "Invalid CLI arguments.");
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return undefined;
    if (this.active) throw new BackendError("workflow_busy", "An AI workflow is already running.");
    return this.request<CLICommand>("cli.command", { ...input, trusted: true }, ticket);
  }

  async loadQueue(ticket = this.session.identity.capture()): Promise<WorkflowStatus | undefined> {
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return undefined;
    const result = await this.request("queue.settings.get", { trusted: true }, ticket);
    if (result && this.trusted()) this.publish(result);
    return this.trusted() ? result : undefined;
  }

  async setQueue(settings: QueuePatch, ticket = this.session.identity.capture()): Promise<void> {
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return;
    if (!validQueuePatch(settings, this.snapshot?.queueSettings)) throw new BackendError("invalid_params", "Invalid queue settings.");
    if (this.active) throw new BackendError("workflow_busy", "An AI workflow is already running.");
    const result = await this.request("queue.settings.set", { trusted: true, settings }, ticket);
    if (result && this.trusted()) this.publish(result);
  }

  async continueQueue(input: WorkflowInput, token: CancellationToken, progress: (message: string) => void,
    ticket = this.session.identity.capture()): Promise<WorkflowStatus | undefined> {
    if (!validWorkflowInput(input)) throw new BackendError("invalid_params", "Invalid queue continuation arguments.");
    if (!ticket.context || !this.current(ticket) || !this.trusted() || token.isCancellationRequested) return undefined;
    if (this.active) throw new BackendError("workflow_busy", "An AI workflow is already running.");
    const active: ActiveWorkflow = { ticket, cancelled: false, abort: new AbortController() };
    this.active = active;
    const listener = token.onCancellationRequested(() => { void this.cancel(); });
    try {
      let status = this.snapshot;
      while (this.current(active.ticket) && this.trusted() && !active.cancelled) {
        const current = active.ticket;
        if (status?.workflow?.state === "running") {
          progress(status.workflow.message); await this.pause();
          if (active.cancelled || !this.trusted()) break;
          status = await this.request("workflow.status", { trusted: true, workflowId: active.id }, current);
        } else {
          let evidenceFingerprint: string | undefined;
          if (status?.workflow?.result) {
            const review = await this.client.request<ProposalReview>("proposal.get", { unsavedDocuments: this.unsaved?.() ?? input.unsavedDocuments }, current.context);
            if (!this.current(current) || !this.session.identity.accept(current, review, "read")) break;
            evidenceFingerprint = review.evidenceFingerprint;
          }
          if (active.cancelled || !this.current(current) || !this.trusted()) break;
          const reply = await this.client.request<WorkflowStatus & { decision?: DecisionResult }>("queue.continue",
            { ...input, unsavedDocuments: this.unsaved?.() ?? input.unsavedDocuments, trusted: true, ...(evidenceFingerprint ? { evidenceFingerprint } : {}) }, current.context, { signal: active.abort!.signal });
          if (!this.current(current)) break;
          if (reply.decision) {
            if (!sameContext(reply, reply.decision) || !this.session.acceptDecision(current, reply.decision)) break;
            active.ticket = this.session.identity.capture();
          } else if (!this.session.identity.accept(current, reply, "read")) break;
          status = reply;
        }
        active.id = status?.workflow?.id;
        if (active.cancelled) { await this.cancel(); break; }
        if (!status || !this.current(active.ticket) || !this.trusted()) break;
        this.publish(status);
        if (status.continuation?.state !== "running") return status;
      }
      await this.cancel();
      return undefined;
    } catch (error) {
      if (!this.current(active.ticket)) return undefined;
      if (!this.trusted()) { await this.cancel(); return undefined; }
      if (active.cancelled) { await this.cancel(); return undefined; }
      this.report(error);
      if (this.snapshot?.continuation) {
        this.snapshot.continuation = { state: "stopped", reason: String(error), ready: false }; this.changed();
      }
      throw error;
    } finally { listener.dispose(); if (this.active === active) this.active = undefined; }
  }

  sync(): void {
    if (this.snapshot && !sameContext(this.snapshot, this.session.identity.context)) {
      this.snapshot = undefined; this.changed();
    }
  }

  async run(kind: WorkflowKind, input: WorkflowInput, token: CancellationToken,
    progress: (message: string) => void, ticket = this.session.identity.capture()): Promise<WorkflowStatus | undefined> {
    const interaction = kind === "conversation.send" || kind === "prompt.rephrase";
    if (kind.startsWith("queue.") || kind === "cancel" || kind === "purpose.apply" || kind === "purpose.reject"
      || kind === "conversation.history" || kind === "cli.command"
      || (interaction && (input.focus !== undefined || input.request !== undefined || input.idle !== undefined))
      || (kind === "conversation.send" ? input.message === undefined : input.message !== undefined)
      || input.draft !== undefined
      || !validWorkflowInput(input) || (kind === "purpose" && input.idle === undefined)) {
      throw new BackendError("invalid_params", "Invalid AI workflow arguments.");
    }
    if (this.active) throw new BackendError("workflow_busy", "An AI workflow is already running.");
    if (!ticket.context || !this.current(ticket) || !this.trusted() || token.isCancellationRequested) return undefined;
    const active: ActiveWorkflow = { ticket, cancelled: false };
    this.active = active;
    const listener = token.onCancellationRequested(() => { void this.cancel(); });
    try {
      const params = kind === "purpose" || interaction ? { ...input, trusted: true } : { ...input, kind, trusted: true };
      const started = await this.client.request<WorkflowStatus>(interaction ? kind : kind === "purpose"
        ? "purpose.propose" : "workflow.start", params, ticket.context);
      active.id = sameContext(started, ticket.context) ? started.workflow?.id : undefined;
      if (active.cancelled || !this.trusted()) await this.cancel();
      if (!this.trusted()) return undefined;
      let status = this.current(ticket) && this.trusted() && this.session.identity.accept(ticket, started, "read")
        ? started : undefined;
      while (status?.workflow?.state === "running" && this.current(ticket) && this.trusted()) {
        progress(status.workflow.message); this.publish(status);
        await this.pause();
        status = await this.request("workflow.status", { trusted: true, workflowId: active.id }, ticket);
      }
      if (!this.trusted()) { await this.cancel(); return undefined; }
      if (status && this.current(ticket)) {
        this.publish(status);
        if (status.workflow?.sourceChanged) this.session.markSaved("conversation source changes");
        return status;
      }
      return undefined;
    } catch (error) {
      if (!this.current(ticket) || !this.trusted()) return undefined;
      this.report(error); throw error;
    } finally { listener.dispose(); if (this.active === active) this.active = undefined; }
  }

  async decidePurpose(method: "purpose.apply" | "purpose.reject", idle: boolean, unsavedDocuments: string[],
    trusted: boolean): Promise<string | undefined> {
    const ticket = this.session.identity.capture(), job = this.snapshot?.workflow;
    if (!ticket.context || !this.current(ticket)) return undefined;
    if (this.active) throw new BackendError("workflow_busy", "An AI workflow is already running.");
    if (job?.result?.round !== "purpose") throw new BackendError("purpose_missing", "No purpose-comment candidate is selected.");
    const active: ActiveWorkflow = { ticket, cancelled: false };
    this.active = active;
    try {
      const result = await this.client.request<DecisionResult & { decision: string; skipped: string[] }>(method,
        { workflowId: job.id, idle, unsavedDocuments, trusted }, ticket.context);
      if (!this.current(ticket) || !this.session.acceptDecision(ticket, result)) return undefined;
      this.snapshot = undefined; this.changed();
      const message = `Purpose comments ${result.decision}.${result.decision === "applied" ? " Analyse Project to refresh source facts." : ""}`
        + (result.skipped.length ? ` Files left unchanged: ${result.skipped.join(", ")}.` : "");
      this.diagnostic(message);
      return message;
    } catch (error) {
      if (!this.current(ticket)) return undefined;
      this.report(error); throw error;
    } finally { if (this.active === active) this.active = undefined; }
  }

  async cancel(): Promise<void> {
    const active = this.active;
    if (!active) return;
    active.cancelled = true;
    active.abort?.abort();
    if ((!active.id && !active.abort) || !this.session.identity.isCurrent(active.ticket)) return;
    try {
      const status = await this.client.request<WorkflowStatus>("workflow.cancel", { trusted: true,
        ...(active.id ? { workflowId: active.id } : {}) }, active.ticket.context);
      if (this.current(active.ticket) && this.trusted()) this.publish(status);
    }
    catch (error) { if (this.current(active.ticket) && this.trusted()) this.report(error); }
  }

  private current(ticket: SessionTicket): boolean { return !this.disposed && this.session.identity.isCurrent(ticket); }

  private async request<T extends { sessionId: string; modelRevision: number; targetId: string | null } = WorkflowStatus>(
    method: string, params: object, ticket: SessionTicket): Promise<T | undefined> {
    if (!this.current(ticket)) return undefined;
    try {
      const result = await this.client.request<T>(method, params, ticket.context);
      return this.current(ticket) && this.trusted() && this.session.identity.accept(ticket, result, "read") ? result : undefined;
    } catch (error) {
      if (!this.current(ticket) || !this.trusted()) return undefined;
      throw error;
    }
  }

  private publish(status: WorkflowStatus): void {
    this.snapshot = status; this.changed();
    const error = status.workflow?.error;
    if (error) this.diagnostic(`${error.code}: ${error.message}\n${JSON.stringify(error.details)}`);
  }

  private report(error: unknown): void {
    this.diagnostic(error instanceof BackendError ? `${error.code}: ${error.message}\n${JSON.stringify(error.details)}` : String(error));
  }

  dispose(): void { void this.cancel(); this.disposed = true; this.snapshot = undefined; }
}
