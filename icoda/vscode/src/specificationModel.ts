import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError, SessionContext } from "./protocol";
import { sameContext, SessionTicket } from "./sessionState";
import { Phase, ProviderInventory, ProviderSelection, SavedSpecification, Specification, SpecificationNode,
  SpecificationSnapshot, Validation, ProviderChoice, providerChoice, specificationNodes } from "./specificationData";

/** Only the backend validates documents and determines phase availability. */
export class SpecificationModel {
  snapshot?: SpecificationSnapshot;
  private observed?: SessionContext;
  private sequence = 0;
  private disposed = false;
  private message = "Open an ICODA project to see its specification.";

  constructor(readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly changed: () => void, private readonly trusted: () => boolean = () => true) {}

  async selectProvider(choice: ProviderChoice, ticket = this.session.identity.capture()): Promise<ProviderInventory | undefined> {
    if (!ticket.context || !this.current(ticket) || !this.trusted()) return undefined;
    if (!providerChoice(choice)) throw new BackendError("invalid_params", "Invalid provider/model/executable selection.");
    try {
      const result = await this.request<ProviderInventory>("providers.select", { ...choice, trusted: true }, ticket);
      if (!this.trusted()) return undefined;
      if (this.snapshot) { this.snapshot.providers = result; this.changed(); }
      return result;
    } catch (error) {
      if (!this.current(ticket) || !this.trusted()) return undefined;
      throw error;
    }
  }

  async sync(force = false): Promise<void> {
    if (this.disposed) return;
    const ticket = this.session.identity.capture();
    if (!force && sameContext(ticket.context, this.observed)) { this.changed(); return; }
    this.observed = ticket.context;
    const sequence = ++this.sequence;
    this.snapshot = undefined;
    this.message = ticket.context ? "Loading specification…" : "Open an ICODA project to see its specification.";
    this.changed();
    if (!ticket.context) return;
    const results = await Promise.allSettled([this.request<Specification>("spec.get", {}, ticket),
      this.request<Phase>("phase.get", {}, ticket), this.request<ProviderInventory>("providers.list", {}, ticket)]);
    if (!this.current(ticket) || sequence !== this.sequence) return;
    const [spec, phase, providers] = results;
    this.snapshot = { spec: spec.status === "fulfilled" ? spec.value : undefined,
      phase: phase.status === "fulfilled" ? phase.value : undefined,
      providers: providers.status === "fulfilled" ? providers.value : undefined,
      errors: results.flatMap(result => result.status === "rejected" ? [`${String(result.reason)}. Validate Specification to retry.`] : []) };
    this.changed();
  }

  items(selection?: ProviderSelection): SpecificationNode[] {
    return this.disposed ? [] : this.snapshot ? specificationNodes(this.snapshot, selection) : [{ id: "state", label: this.message }];
  }

  current(ticket: SessionTicket): boolean { return !this.disposed && this.session.identity.isCurrent(ticket); }

  async request<T extends SessionContext>(method: string, params: object, ticket = this.session.identity.capture(),
    mutation = false): Promise<T> {
    this.requireCurrent(ticket);
    const result = await this.client.request<T>(method, params, ticket.context);
    this.requireCurrent(ticket);
    const accepted = mutation ? this.session.acceptWorkflow(ticket, result) : this.session.identity.accept(ticket, result, "read");
    if (!accepted) throw new BackendError("stale_revision", "The project changed. Reopen the specification to refresh.");
    return result;
  }

  requireCurrent(ticket: SessionTicket): void {
    if (!ticket.context || !this.current(ticket)) {
      throw new BackendError("stale_revision", "The project or revision changed. Reopen the specification; unsaved edits are kept.");
    }
  }

  async save(document: unknown, ticket: SessionTicket, unsavedDocuments: string[]): Promise<SavedSpecification> {
    this.requireCurrent(ticket);
    let result: SavedSpecification;
    try {
      result = await this.client.request<SavedSpecification>("spec.save",
        { document, trusted: true, postSave: true, unsavedDocuments }, ticket.context);
    } catch (error) {
      if (!(error instanceof BackendError) || error.code !== "cancelled" || error.details.saved !== true) throw error;
      result = error.details as unknown as SavedSpecification;
    }
    this.requireCurrent(ticket);
    if (!this.session.acceptAnalysis(ticket, result)) {
      throw new BackendError("stale_revision", "The project changed. Reopen the specification to refresh.");
    }
    return result;
  }

  async refreshSaved(ticket: SessionTicket): Promise<void> {
    this.requireCurrent(ticket);
    await this.session.listTargets(this.client);
    if (this.current(ticket)) await this.sync(true);
  }

  showValidation(result: Validation): void {
    if (!this.snapshot?.spec || !sameContext(result, this.session.identity.context)) return;
    Object.assign(this.snapshot.spec, { valid: result.valid, findings: result.findings });
    this.changed();
  }

  dispose(): void { this.disposed = true; this.sequence++; this.snapshot = undefined; }
}
