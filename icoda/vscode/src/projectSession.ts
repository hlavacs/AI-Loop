import { BackendClient, RequestOptions } from "./backendClient";
import {
  AnalysedProject, BackendError, Diagnostic, OpenedProject, ProjectModel,
  SelectedTarget, SessionContext, Target, TargetList, TargetOperationResult, validateProjectCheck,
} from "./protocol";
import { SessionState, SessionTicket } from "./sessionState";
import { DecisionResult } from "./proposalData";
import type { CallViewState } from "./callViewModel";

export interface ProjectData {
  root: string;
  modelState: "none" | "fresh" | "stale" | "analysing";
  staleReason: string;
  entityCount: number;
  edgeCount: number;
  targets: Target[];
}

/** Coordinate project operations without VS Code; the service remains authoritative. */
export class ProjectSession {
  readonly identity: SessionState;
  data?: ProjectData;
  model?: ProjectModel;
  sourceRootId?: string;
  callViewState?: CallViewState;
  private saveSequence = 0;

  constructor(private readonly log: (message: string) => void, private readonly changed: () => void) {
    this.identity = new SessionState(log);
  }

  reset(): void {
    this.identity.reset();
    this.data = undefined;
    this.model = undefined;
    this.sourceRootId = undefined;
    this.callViewState = undefined;
    this.saveSequence = 0;
    this.changed();
  }

  async open(client: Pick<BackendClient, "request">, path: string): Promise<boolean> {
    this.reset();
    const ticket = this.identity.capture();
    const result = await this.currentRequest<OpenedProject>(client, "project.open", { path }, ticket);
    if (!result || !this.identity.accept(ticket, result, "open")) return false;
    this.data = { root: result.root, targets: [], ...modelSummary(result.model, result.cached) };
    this.model = result.model;
    this.sourceRootId = result.sourceRootId;
    this.changed();
    this.log(`Opened ${result.root}; revision ${result.modelRevision}.`);
    await this.listTargets(client);
    return true;
  }

  async analyse(client: Pick<BackendClient, "request">, options: RequestOptions = {}, params: object = {}): Promise<void> {
    const ticket = this.requireProject();
    const previous = this.data!.modelState;
    const saves = this.saveSequence;
    this.data!.modelState = "analysing";
    this.changed();
    try {
      const outcome = await this.requestAnalysis(client, ticket, options, params);
      if (!outcome || !this.acceptAnalysis(ticket, outcome.result, saves)) return;
      if (outcome.error) this.log(outcome.error.message);
      await this.listTargets(client);
      if (outcome.error) throw outcome.error;
    } finally {
      if (this.identity.isCurrent(ticket) && this.data && saves === this.saveSequence) {
        this.data.modelState = previous;
        this.changed();
      }
    }
  }

  markSaved(file: string): void {
    if (!this.data || this.data.modelState === "none") return;
    this.saveSequence++;
    this.data.modelState = "stale";
    this.data.staleReason = `Saved ${file}. Run ICODA: Analyse Project to refresh the model.`;
    this.log(this.data.staleReason);
    this.changed();
  }

  acceptWorkflow(ticket: SessionTicket, result: SessionContext): boolean {
    if (!this.identity.accept(ticket, result, "workflow")) return false;
    this.changed();
    return true;
  }

  acceptDecision(ticket: SessionTicket, result: DecisionResult): boolean {
    if (!this.identity.accept(ticket, result, "workflow")) return false;
    this.model = result.model;
    this.sourceRootId = result.sourceRootId;
    if (this.data) Object.assign(this.data, modelSummary(result.model, true));
    this.changed();
    return true;
  }

  private async requestAnalysis(client: Pick<BackendClient, "request">, ticket: SessionTicket, options: RequestOptions, params: object) {
    try {
      const result = await client.request<AnalysedProject>("project.analyse", params, ticket.context, this.scopedOptions(ticket, options));
      return { result, error: undefined };
    } catch (error) {
      if (!this.identity.isCurrent(ticket)) {
        this.log("Dropped obsolete analysis error.");
        return undefined;
      }
      if (!(error instanceof BackendError) || error.code !== "analysis_failed") throw error;
      return { result: error.details as unknown as AnalysedProject, error };
    }
  }

  async listTargets(client: Pick<BackendClient, "request">): Promise<void> {
    const ticket = this.requireProject();
    const result = await this.currentRequest<TargetList>(client, "targets.list", {}, ticket);
    if (!result || !this.identity.accept(ticket, result, "read")) return;
    this.data!.targets = result.targets;
    this.diagnostics(result.diagnostics);
    this.changed();
  }

  async select(client: Pick<BackendClient, "request">, targetId: string | null): Promise<void> {
    this.identity.invalidate();
    if (this.data?.modelState === "analysing") {
      this.data.modelState = "stale";
      this.data.staleReason = "Analysis superseded by target selection. Run ICODA: Analyse Project to refresh.";
    }
    const ticket = this.requireProject();
    const result = await this.currentRequest<SelectedTarget>(client, "target.select", { targetId }, ticket);
    if (!result || !this.identity.accept(ticket, result, { targetId })) return;
    // The response model is scoped. Keep the whole-project summary from open/analysis.
    this.log(`Selected target ${result.targetId ?? "Whole Project"}; revision ${result.modelRevision}.`);
    this.changed();
  }

  async operate(client: Pick<BackendClient, "request">, method: string, params: object, options: RequestOptions) {
    const ticket = this.requireProject();
    try {
      const result = await client.request<TargetOperationResult>(method, params, ticket.context, this.scopedOptions(ticket, options));
      if (!this.identity.accept(ticket, result, method === "targets.refresh" ? "refresh" : "read")) return;
      if (method === "tests.run" || (method === "build.run" && ticket.context?.targetId === null)) {
        validateProjectCheck(result.check, method === "tests.run" ? "tests" : "build");
      }
      if (method === "targets.refresh") this.data!.targets = result.targets;
      this.log(result.message);
      this.changed();
      return result;
    } catch (error) {
      if (this.identity.isCurrent(ticket)) throw error;
      this.log("Dropped obsolete target operation error.");
      return undefined;
    }
  }

  private requireProject(): SessionTicket {
    const ticket = this.identity.capture();
    if (!ticket.context || !this.data) throw new BackendError("project_not_open", "Open a project first.");
    return ticket;
  }

  private scopedOptions(ticket: SessionTicket, options: RequestOptions): RequestOptions {
    return { ...options, progress: message => {
      if (this.identity.isCurrent(ticket)) options.progress?.(message);
    } };
  }

  private async currentRequest<T>(client: Pick<BackendClient, "request">, method: string, params: object,
    ticket: SessionTicket): Promise<T | undefined> {
    try { return await client.request<T>(method, params, ticket.context); }
    catch (error) {
      if (this.identity.isCurrent(ticket)) throw error;
      this.log(`Dropped obsolete ${method} error.`);
      return undefined;
    }
  }

  acceptAnalysis(ticket: SessionTicket, result: AnalysedProject, saves = this.saveSequence): boolean {
    if (!this.identity.accept(ticket, result, "analyse")) return false;
    const savedReason = this.data!.staleReason;
    Object.assign(this.data!, modelSummary(result.model, true));
    this.model = result.model;
    this.sourceRootId = result.sourceRootId;
    if (saves !== this.saveSequence) {
      this.data!.modelState = "stale";
      this.data!.staleReason = savedReason;
    }
    this.diagnostics(result.diagnostics);
    this.log(`Analysis revision ${result.modelRevision}: ${this.data!.entityCount} entities, ${this.data!.edgeCount} edges; ${this.data!.modelState}.`);
    this.changed();
    return true;
  }

  private diagnostics(diagnostics: Diagnostic[]): void {
    for (const diagnostic of diagnostics) {
      this.log(`${diagnostic.code ?? "analysis"}${diagnostic.file ? ` (${diagnostic.file})` : ""}: ${diagnostic.message}`);
    }
  }
}

function modelSummary(model: ProjectModel, available: boolean): Omit<ProjectData, "root" | "targets"> {
  return {
    modelState: !available ? "none" : model.stale ? "stale" : "fresh",
    staleReason: model.stale_reason,
    entityCount: model.entities.length,
    edgeCount: model.edges.length,
  };
}
