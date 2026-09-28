import { ViewState } from "./viewState";
import { GraphInteractions } from "./graphInteractions";
import { viewError } from "./viewErrors";
import { BackendClient } from "./backendClient";
import { BackendError, SessionContext, SourceReference } from "./protocol";
import { ProjectSession } from "./projectSession";
import { sameContext } from "./sessionState";
import { Viewport } from "./callViewMessages";
import { ClassViewMessage } from "./classViewMessages";

export interface ClassSource {
  usr: string; entityId: string; file: string | null; sourceRootId: string; line: number;
}
export interface ClassMember extends ClassSource {
  name: string; kind: string; declaration: string; status: string; visibility: string | null;
}
export interface ClassNode extends Partial<ClassSource> {
  id: string; label: string; kind: "class" | "struct" | "cluster";
  x: number; y: number; width: number; height: number; expandable: boolean;
  count?: number; members?: ClassMember[];
}
export interface ClassViewResponse extends SessionContext {
  view: "class"; sourceRootId: string; clusterId: string | null; overview: boolean;
  clusterPath: { id: string; label: string }[]; nodes: ClassNode[];
  edges: { source: string; target: string; count: number; kind: "inheritance" | "composition" | "usage" }[];
  bounds: { x: number; y: number }; width: number; height: number; stale: boolean; staleReason: string;
  headerHeight: number; memberHeight: number;
}

/** Python owns grouping and geometry. Each visible level retains its own camera in this panel. */
export class ClassViewModel {
  readonly interactions = new GraphInteractions(this.session, this.client, this.changed, this.log);
  graph?: ClassViewResponse;
  clusterId: string | null = null;
  selected: string | null = null;
  viewport?: Viewport;
  version = 0;
  loading = false;
  error = "";
  private readonly persistence = new ViewState<{ clusterId: string | null; cameras: { clusterId: string | null; viewport: Viewport }[] }>(
    "class", this.session, this.client, this.log);
  private observed?: SessionContext;
  private disposed = false;
  private requestNumber = 0;
  private readonly cameras = new Map<string | null, Viewport>();

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
    this.clusterId = this.selected = null;
    this.viewport = undefined;
    this.cameras.clear();
    this.graph = undefined;
    this.loading = true;
    this.version++;
    this.changed();
    const ticket = this.session.identity.capture();
    const state = await this.persistence.restore();
    if (this.disposed || !this.session.identity.isCurrent(ticket)) return;
    if (state) {
      this.clusterId = state.clusterId;
      for (const camera of state.cameras) this.cameras.set(camera.clusterId, camera.viewport);
      this.viewport = this.cameras.get(this.clusterId);
    }
    await this.load();
  }

  accepts(message: ClassViewMessage): boolean {
    if (this.disposed) return false;
    if (message.type === "ready") return true;
    if (!this.graph || this.loading || message.version !== this.version
        || !sameContext(this.observed, this.session.identity.context)) return false;
    if (message.type === "select") return Boolean(this.source(message.id));
    if (message.type === "enter") return this.graph.nodes.some(node => node.id === message.id && node.expandable);
    return true;
  }

  private source(id: string): SourceReference | undefined {
    for (const node of this.graph?.nodes ?? []) {
      if (node.expandable) continue;
      const source = node.usr === id ? node : node.members?.find(member => member.usr === id);
      if (source?.usr && source.file && source.sourceRootId) {
        return { usr: source.usr, sourceRootId: source.sourceRootId };
      }
    }
    return undefined;
  }

  select(id: string): SourceReference | undefined {
    const ref = this.source(id);
    if (!ref) return undefined;
    this.selected = id;
    this.changed();
    return ref;
  }

  async control(message: ClassViewMessage): Promise<void> {
    if (!this.accepts(message)) return;
    if (message.type === "graphOptions") {
      await this.interactions.control(message); this.changed(); return;
    }
    if (message.type === "viewport") { this.viewport = message.viewport; this.persist(); return; }
    if (message.type === "fit") { this.fit(message.width, message.height); this.persist(); return; }
    if (message.type === "enter" || message.type === "back") {
      await this.navigate(message.type === "back" ? null : message.id);
    }
  }

  private async navigate(clusterId: string | null): Promise<void> {
    if (this.viewport) this.cameras.set(this.clusterId, this.viewport);
    this.clusterId = clusterId;
    this.viewport = this.cameras.get(clusterId);
    this.selected = null;
    await this.load();
    this.persist();
    await this.saveState();
  }

  private persist(): void {
    if (this.viewport) this.cameras.set(this.clusterId, this.viewport);
    this.persistence.schedule({ clusterId: this.clusterId,
      cameras: [...this.cameras].slice(-512).map(([clusterId, viewport]) => ({ clusterId, viewport })) });
  }

  async saveState(): Promise<void> { await this.persistence.flush(); }

  private fit(width: number, height: number): void {
    if (!this.graph) return;
    const scale = Math.min(2, Math.max(0.1, Math.min((width - 48) / this.graph.width, (height - 48) / this.graph.height)));
    this.viewport = { scale, x: (width - this.graph.width * scale) / 2 - this.graph.bounds.x * scale,
      y: (height - this.graph.height * scale) / 2 - this.graph.bounds.y * scale };
    this.changed();
  }

  private async load(): Promise<void> {
    const ticket = this.session.identity.capture();
    if (this.disposed || !ticket.context) return;
    const request = ++this.requestNumber;
    this.version++;
    this.loading = true;
    this.graph = undefined;
    this.error = "";
    this.changed();
    const current = () => !this.disposed && request === this.requestNumber && this.session.identity.isCurrent(ticket);
    try {
      const result = await this.client.request<ClassViewResponse>("view.get", { view: "class", clusterId: this.clusterId }, ticket.context);
      if (current() && this.session.identity.accept(ticket, result, "read")) this.graph = result;
    } catch (error) {
      if (current()) {
        this.error = error instanceof BackendError && error.code === "model_unavailable"
          ? "Run ICODA: Analyse Project to display its classes." : `Class View: ${viewError(error)}`;
        this.log(this.error);
      }
    } finally {
      if (current()) { this.loading = false; this.changed(); }
    }
  }

  render() {
    return { interactions: this.interactions.snapshot(this.graph, this.selected),
      type: "render", version: this.version, graph: this.graph, selected: this.selected,
      viewport: this.viewport, loading: this.loading, message: this.status() };
  }

  private status(): string {
    if (!this.session.identity.context) return "Open a workspace folder, then run ICODA: Open Project.";
    if (this.error) return this.error;
    if (this.loading) return "Loading Class View…";
    if (!this.graph) return "Run ICODA: Analyse Project to display its source structure.";
    if (!this.graph.nodes.length) return "No classes or structs in this model. Analyse the project or choose another target.";
    if (this.session.data?.modelState === "stale" || this.graph.stale) {
      return `Stale model: ${this.session.data?.staleReason || this.graph.staleReason}`;
    }
    return `${this.graph.nodes.length} visible nodes · Select a cluster to expand; select a class or member to open source.`;
  }

  dispose(): void { this.persistence.dispose(); this.interactions.dispose(); this.disposed = true; this.requestNumber++; }
}
