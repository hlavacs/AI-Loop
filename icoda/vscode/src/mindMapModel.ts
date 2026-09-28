import { ViewState } from "./viewState";
import { GraphInteractions } from "./graphInteractions";
import { viewError } from "./viewErrors";
import { BackendClient } from "./backendClient";
import { BackendError, SessionContext, SourceReference } from "./protocol";
import { ProjectSession } from "./projectSession";
import { sameContext } from "./sessionState";
import { Viewport } from "./callViewMessages";
import { MindMapMessage } from "./mindMapMessages";
import { StepRecord } from "./proposalData";

export interface MindMapRequirement {
  id: string; title: string; uncovered: boolean | null; useCaseIds: string[];
}
export interface MindMapStep extends StepRecord {
  phase: string; request: string; entities_added: string[]; entities_changed: string[];
  entities_renamed: [string, string][]; build_ok: boolean | null; test_ok: boolean | null;
}

export function mindMapStepText(record: MindMapStep): string {
  const status = (ok: boolean | null) => ok === null ? "not run" : ok ? "passed" : "failed";
  return [`Step ${record.number}: ${record.decision} — ${record.title}`, `Phase: ${record.phase}`,
    `Commit: ${record.commit || "not recorded"}`, `Request:\n${record.request}`, `Rationale:\n${record.rationale}`,
    `Reason:\n${record.reason}`, `Files:\n${record.files.join("\n")}`,
    `Entities added:\n${record.entities_added.join("\n")}`, `Entities changed:\n${record.entities_changed.join("\n")}`,
    `Entities renamed:\n${record.entities_renamed.map(([before, after]) => `${before} → ${after}`).join("\n")}`,
    `Build: ${status(record.build_ok)}\n${record.build_output}`, `Tests: ${status(record.test_ok)}\n${record.test_output}`,
  ].join("\n\n");
}

export interface MindMapNode {
  id: string; label: string; qualifiedName: string; kind: "cluster" | "file" | "class" | "function";
  parent: string | null; children: string[]; depth: number;
  x: number; y: number; width: number; height: number; expandable: boolean; expanded: boolean;
  status: string; requirementIds: string[]; requirements: MindMapRequirement[]; useCaseIds: string[];
  step: { number: number; title: string } | null;
  usr: string | null; file: string | null; sourceRootId: string; line: number;
}
export interface MindMapResponse extends SessionContext {
  view: "mindmap"; sourceRootId: string; nodes: MindMapNode[]; totalNodes: number;
  edges: { source: string; target: string }[];
  bounds: { x: number; y: number }; width: number; height: number; stale: boolean; staleReason: string;
  empty: boolean; emptyReason: string; requirements: MindMapRequirement[]; hasSteps: boolean; messages: string[];
}

/** The backend owns hierarchy, layout and expansion. This model only routes actions and the camera. */
export class MindMapModel {
  readonly interactions = new GraphInteractions(this.session, this.client, this.changed, this.log);
  graph?: MindMapResponse;
  selected: string | null = null;
  viewport?: Viewport;
  version = 0;
  loading = false;
  error = "";
  private readonly persistence = new ViewState<{ viewport: Viewport | null }>("mindmap", this.session, this.client, this.log);
  private observed?: SessionContext;
  private disposed = false;
  private requestNumber = 0;

  constructor(private readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly log: (message: string) => void, private readonly changed: () => void) {}

  async sync(): Promise<void> {
    const context = this.session.identity.context;
    if (this.disposed || !context) return;
    if (sameContext(context, this.observed)) {
      if (!this.persistence.bound) await this.persistence.restore();
      if (!this.disposed) this.changed();
      return;
    }
    this.observed = context;
    this.selected = null;
    this.viewport = undefined;
    this.graph = undefined;
    this.loading = true;
    this.version++;
    this.changed();
    const ticket = this.session.identity.capture();
    const state = await this.persistence.restore();
    if (this.disposed || !this.session.identity.isCurrent(ticket)) return;
    this.viewport = state?.viewport ?? undefined;
    await this.load("view.get", { view: "mindmap" });
  }

  accepts(message: MindMapMessage): boolean {
    if (this.disposed) return false;
    if (message.type === "ready") return true;
    if (!this.graph || this.loading || message.version !== this.version
        || !sameContext(this.observed, this.session.identity.context)) return false;
    if (message.type === "select" || message.type === "setExpanded" || message.type === "openStep") {
      const node = this.graph.nodes.find(item => item.id === message.nodeId);
      return Boolean(node && (message.type === "select" || (message.type === "openStep" ? node.step : node.expandable)));
    }
    return true;
  }

  select(nodeId: string): SourceReference | undefined {
    const node = this.graph?.nodes.find(item => item.id === nodeId);
    if (!node || this.disposed || this.loading || !sameContext(this.observed, this.session.identity.context)) return undefined;
    this.selected = nodeId;
    this.changed();
    if (!node.file) return undefined;
    return node.usr ? { usr: node.usr, sourceRootId: node.sourceRootId }
      : { file: node.file, line: node.line, sourceRootId: node.sourceRootId };
  }

  async control(message: MindMapMessage): Promise<void> {
    if (!this.accepts(message)) return;
    if (message.type === "graphOptions") {
      await this.interactions.control(message); this.changed(); return;
    }
    if (message.type === "viewport") { this.viewport = message.viewport; this.persist(); return; }
    if (message.type === "fit") { this.fit(message.width, message.height); this.persist(); return; }
    if (message.type === "setExpanded") {
      await this.load("mindmap.setExpanded", { nodeId: message.nodeId, expanded: message.expanded });
    }
  }

  async openStep(message: MindMapMessage): Promise<MindMapStep | undefined> {
    if (message.type !== "openStep" || !this.accepts(message)) return undefined;
    const ticket = this.session.identity.capture();
    const current = () => this.session.identity.isCurrent(ticket) && this.accepts(message);
    try {
      const result = await this.client.request<SessionContext & { nodeId: string; record: MindMapStep }>(
        "mindmap.step", { nodeId: message.nodeId }, ticket.context);
      if (current() && this.session.identity.accept(ticket, result, "read") && result.nodeId === message.nodeId) {
        this.error = "";
        this.changed();
        return result.record;
      }
    } catch (error) {
      if (current()) { this.reportError(error); this.changed(); }
    }
    return undefined;
  }

  private persist(): void { this.persistence.schedule({ viewport: this.viewport ?? null }); }

  async saveState(): Promise<void> { await this.persistence.flush(); }

  private fit(width: number, height: number): void {
    if (!this.graph) return;
    const scale = Math.min(2, Math.max(0.1, Math.min((width - 48) / this.graph.width, (height - 48) / this.graph.height)));
    this.viewport = { scale, x: (width - this.graph.width * scale) / 2, y: (height - this.graph.height * scale) / 2 };
    this.changed();
  }

  private async load(method: string, params: Record<string, unknown>): Promise<void> {
    const ticket = this.session.identity.capture();
    if (this.disposed || !ticket.context) return;
    const request = ++this.requestNumber, previous = this.graph;
    this.version++;
    this.loading = true;
    this.graph = undefined;
    this.error = "";
    this.changed();
    const current = () => !this.disposed && request === this.requestNumber && this.session.identity.isCurrent(ticket);
    try {
      const result = await this.client.request<MindMapResponse>(method, params, ticket.context);
      if (current() && this.session.identity.accept(ticket, result, "read")) {
        this.graph = result;
        if (!result.nodes.some(node => node.id === this.selected)) this.selected = null;
      }
    } catch (error) {
      if (current()) { this.graph = previous; this.reportError(error); }
    } finally {
      if (current()) { this.loading = false; this.changed(); }
    }
  }

  private reportError(error: unknown): void {
    this.error = error instanceof BackendError && error.code === "model_unavailable"
      ? "Run ICODA: Analyse Project to display its Mind Map." : `Mind Map: ${viewError(error)}`;
    this.log(this.error);
  }

  render() {
    return { interactions: this.interactions.snapshot(this.graph, this.selected),
      type: "render", version: this.version, graph: this.graph, selected: this.selected,
      viewport: this.viewport, loading: this.loading, message: this.status() };
  }

  private status(): string {
    if (!this.session.identity.context) return "Open a workspace folder, then run ICODA: Open Project.";
    if (this.error) return this.error;
    if (this.loading) return "Loading Mind Map…";
    if (!this.graph) return "Analyse a project to display its Mind Map.";
    const state = this.session.data?.modelState === "stale" || this.graph.stale
      ? `Stale model: ${this.session.data?.staleReason || this.graph.staleReason}` : "";
    const summary = this.graph.empty ? this.graph.emptyReason
      : `${this.graph.nodes.length} of ${this.graph.totalNodes} nodes · Toggle +/− to expand; select a node to open source.`;
    return [state, summary, ...this.graph.messages].filter(Boolean).join(" · ");
  }

  dispose(): void { this.persistence.dispose(); this.interactions.dispose(); this.disposed = true; this.requestNumber++; }
}
