import { BackendError } from "./protocol";
import { SessionTicket } from "./sessionState";
import { Specification, Validation } from "./specificationData";
import { SpecificationModel } from "./specificationModel";

interface Draft { ticket: SessionTicket; text: string; modified: number }

/** Native documents have session/revision-bound drafts; no direct filesystem write can bypass the core. */
export class SpecificationDocuments {
  private readonly drafts = new Map<string, Draft>();

  constructor(private readonly model: SpecificationModel, private readonly trusted: () => boolean,
    private readonly unsaved: (key: string) => string[] = () => [],
    private readonly report: (error: BackendError) => void = () => {}) {}

  async open(key: string): Promise<void> {
    if (this.drafts.has(key)) return; // Never replace an open editor's unsaved buffer.
    const ticket = this.model.session.identity.capture();
    const spec = await this.model.request<Specification>("spec.get", {}, ticket);
    this.drafts.set(key, { ticket, text: JSON.stringify(spec.document, null, 2) + "\n", modified: Date.now() });
  }

  read(key: string): string { return this.draft(key).text; }
  currentKey(): string | undefined {
    return [...this.drafts].find(([, draft]) => this.model.current(draft.ticket))?.[0];
  }
  modified(key: string): number { return this.draft(key).modified; }
  close(key: string): void { this.drafts.delete(key); }
  dispose(): void { this.drafts.clear(); }

  async validate(key: string, text: string): Promise<Validation> {
    const draft = this.draft(key);
    const document = parseSpecification(text);
    const result = await this.model.request<Validation>("spec.validate", { document }, draft.ticket);
    this.model.showValidation(result);
    return result;
  }

  async save(key: string, text: string): Promise<void> {
    if (!this.trusted()) throw new BackendError("workspace_untrusted", "Trust the workspace before saving the specification.");
    const draft = this.draft(key), ticket = draft.ticket, document = parseSpecification(text);
    const validation = await this.model.request<Validation>("spec.validate", { document }, ticket);
    this.model.showValidation(validation);
    if (!validation.valid) throw new BackendError("invalid_specification", validation.findings.map(item => item.message).join("\n"));
    if (!this.trusted()) throw new BackendError("workspace_untrusted", "Workspace trust changed; specification was not saved.");
    const result = await this.model.save(document, ticket, this.unsaved(key));
    draft.ticket = this.model.session.identity.capture();
    draft.text = text;
    draft.modified = Date.now();
    if (result.postSaveError) {
      const error = result.postSaveError;
      this.report(new BackendError(error.code, `Specification saved. ${error.message}`, error.details));
    }
    await this.model.refreshSaved(draft.ticket);
  }

  private draft(key: string): Draft {
    const draft = this.drafts.get(key);
    if (!draft) throw new BackendError("invalid_params", "Unknown specification document. Use ICODA: Open Specification.");
    return draft;
  }
}

export function parseSpecification(text: string): unknown {
  try { return JSON.parse(text); }
  catch { throw new BackendError("invalid_specification", "Specification must contain valid JSON. Your edits are kept."); }
}
