import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { SessionContext, SourceReference } from "./protocol";
import { sameContext } from "./sessionState";
import { CoverageResponse, EvidenceKind, EvidenceNode, EvidenceSelection, IssuesResponse,
  coverageNodes, issueNodes, messageNode } from "./evidenceData";

/** Read-only evidence routing shares the same session tickets as the diagram views. */
export class EvidenceModel {
  version = 0;
  private nodes: EvidenceNode[] = [messageNode("closed", "Open an ICODA project to see evidence.")];
  private observed?: SessionContext;
  private disposed = false;
  private loaded = false;
  private staleReason = "";

  constructor(readonly kind: EvidenceKind, private readonly session: ProjectSession,
    private readonly client: Pick<BackendClient, "request">, private readonly log: (message: string) => void,
    private readonly changed: () => void) {}

  async sync(force = false): Promise<void> {
    if (this.disposed) return;
    const context = this.session.identity.context;
    if (!force && sameContext(context, this.observed)) { this.changed(); return; }
    this.observed = context;
    this.loaded = false;
    this.staleReason = "";
    this.version++;
    this.nodes = [messageNode(context ? "loading" : "closed", context
      ? "Loading evidence…" : "Open an ICODA project to see evidence.")];
    this.changed();
    if (context) await this.load(this.version);
  }

  private async load(version: number): Promise<void> {
    const ticket = this.session.identity.capture();
    const current = () => !this.disposed && version === this.version && this.session.identity.isCurrent(ticket);
    try {
      const result = await this.client.request<IssuesResponse | CoverageResponse>(
        this.kind === "issues" ? "issues.list" : "coverage.get", {}, ticket.context);
      if (!current() || !this.session.identity.accept(ticket, result, "read")) return;
      this.nodes = this.kind === "issues" ? issueNodes(result as IssuesResponse) : coverageNodes(result as CoverageResponse);
      this.staleReason = result.stale ? result.staleReason || "Retained analysis" : "";
      this.loaded = true;
    } catch (error) {
      if (current()) {
        const message = `Unable to load ${this.kind}: ${String(error)}. Use Refresh to retry.`;
        this.log(message);
        this.nodes = [messageNode("error", message)];
      }
    } finally { if (current()) this.changed(); }
  }

  items(): EvidenceNode[] {
    const stale = this.session.data?.modelState === "stale" ? this.session.data.staleReason : this.staleReason;
    return stale ? [messageNode("stale", `Stale model: ${stale}`), ...this.nodes] : this.nodes;
  }

  select(selection: EvidenceSelection): SourceReference | undefined {
    if (this.disposed || !this.loaded || selection.view !== this.kind || selection.version !== this.version
        || !sameContext(this.observed, this.session.identity.context)) return undefined;
    return findNode(this.nodes, selection.id)?.source;
  }

  dispose(): void { this.disposed = true; this.version++; this.nodes = []; }
}

function findNode(nodes: EvidenceNode[], id: string): EvidenceNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = node.children && findNode(node.children, id);
    if (child) return child;
  }
  return undefined;
}
