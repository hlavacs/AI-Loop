import { GraphInteractions } from "./graphInteractions";
import { viewError } from "./viewErrors";
import { BackendClient } from "./backendClient";
import { BackendError, SessionContext, SourceReference } from "./protocol";
import { ProjectSession } from "./projectSession";
import { SessionTicket } from "./sessionState";
import { Viewport } from "./callViewMessages";
import { FileViewMessage } from "./fileViewMessages";

export interface FileNode {
  id: string; label: string; kind: "file" | "cluster" | "external";
  x: number; y: number; width: number; height: number; expandable: boolean;
  fileCount?: number; name?: string; pinned?: boolean; renamed?: boolean; parentId?: string | null;
  filterMembers?: string[];
  entityId?: string; file?: string | null; sourceRootId?: string; line?: number;
}
export interface FileViewResponse extends SessionContext {
  view: "file"; sourceRootId: string; clusterId: string | null; overview: boolean;
  clusterPath: { id: string; label: string; pinned?: boolean }[]; nodes: FileNode[];
  clusters?: { id: string; label: string; fileCount: number }[];
  edges: { source: string; target: string; count: number; counts: Record<string, number>; label: string }[];
  bounds: { x: number; y: number }; width: number; height: number; stale: boolean; staleReason: string;
}
interface FileReveal extends SessionContext {
  sourceRootId: string; entityId: string; file: string; clusterId: string | null; clusterPath: string[];
}
interface FileViewState extends SessionContext {
  state: { clusterId: string | null; cameras: { clusterId: string | null; viewport: Viewport }[] };
}

/** Python owns grouping and geometry. Each visible level retains its own camera in this panel. */
export class FileViewModel {
  readonly interactions = new GraphInteractions(this.session, this.client, this.changed, this.log);
  graph?: FileViewResponse;
  clusterId: string | null = null;
  selected: string | null = null;
  viewport?: Viewport;
  version = 0;
  loading = false;
  error = "";
  private observed?: SessionTicket;
  private disposed = false;
  private requestNumber = 0;
  private readonly cameras = new Map<string | null, Viewport>();
  private saveTimer?: ReturnType<typeof setTimeout>;
  private savedState = "";

  constructor(private readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly log: (message: string) => void, private readonly changed: () => void) {}

  async sync(): Promise<void> {
    const context = this.session.identity.context;
    if (this.disposed || !context) return;
    if (this.observed && this.session.identity.isCurrent(this.observed)) { this.changed(); return; }
    this.clusterId = this.selected = null;
    this.viewport = undefined;
    this.cameras.clear();
    this.savedState = "";
    clearTimeout(this.saveTimer);
    const ticket = this.session.identity.capture(), request = ++this.requestNumber;
    this.observed = ticket;
    this.graph = undefined;
    this.loading = true;
    this.version++;
    this.changed();
    try {
      const result = await this.client.request<FileViewState>("view.state.get", { view: "file" }, context);
      if (this.disposed || request !== this.requestNumber || !this.session.identity.isCurrent(ticket)) return;
      if (!this.session.identity.accept(ticket, result, "read")) return;
      this.clusterId = result.state.clusterId;
      for (const camera of result.state.cameras) this.cameras.set(camera.clusterId, camera.viewport);
      this.viewport = this.cameras.get(this.clusterId);
      this.savedState = JSON.stringify(result.state);
    } catch (error) {
      if (this.disposed || request !== this.requestNumber || !this.session.identity.isCurrent(ticket)) return;
      this.log(`File View state: ${viewError(error)}`);
    }
    await this.load();
  }

  accepts(message: FileViewMessage): boolean {
    if (this.disposed) return false;
    if (message.type === "ready") return true;
    if (!this.graph || this.loading || message.version !== this.version
        || !this.observed || !this.session.identity.isCurrent(this.observed)) return false;
    if (message.type === "pin" || message.type === "unpin" || message.type === "rename") {
      return this.cluster(message.id) !== undefined;
    }
    if (message.type === "select" || message.type === "enter" || message.type === "assign") {
      return this.graph.nodes.some(node => node.id === message.id
        && (message.type === "enter" ? node.expandable : node.kind === "file"));
    }
    return true;
  }

  cluster(id: string): { id: string; label: string; pinned?: boolean } | undefined {
    if (!id.startsWith("cluster:")) return undefined;
    const node = this.graph?.nodes.find(node => node.id === id && node.kind === "cluster");
    return node ? { id, label: node.name ?? node.label, pinned: node.pinned }
      : this.graph?.clusterPath.find(item => item.id === id);
  }

  async editCluster(message: FileViewMessage, name?: string): Promise<void> {
    if (!this.accepts(message) || !(message.type === "pin" || message.type === "unpin" || message.type === "rename")) return;
    if (message.type === "rename" && !name?.trim()) return;
    await this.load(`cluster.${message.type}`, { clusterId: message.id, viewClusterId: this.clusterId,
      hierarchy: true, ...(message.type === "rename" ? { name } : {}) });
    await this.saveState();
  }

  async assignFile(message: FileViewMessage, clusterId: string | null): Promise<void> {
    if (message.type !== "assign" || !this.accepts(message)
        || (clusterId !== null && !this.graph?.clusters?.some(item => item.id === clusterId))) return;
    await this.load("cluster.assignFile", { file: message.id, clusterId, viewClusterId: this.clusterId, hierarchy: true });
    await this.saveState();
  }

  select(id: string): SourceReference | undefined {
    const node = this.graph?.nodes.find(node => node.id === id && node.kind === "file");
    if (!node?.file || !node.sourceRootId) return undefined;
    this.selected = id;
    this.changed();
    return { file: node.file, sourceRootId: node.sourceRootId, line: node.line ?? 1 };
  }

  async control(message: FileViewMessage): Promise<void> {
    if (!this.accepts(message)) return;
    if (message.type === "graphOptions") {
      await this.interactions.control(message); this.changed(); return;
    }
    if (message.type === "viewport") { this.viewport = message.viewport; this.scheduleSave(); return; }
    if (message.type === "fit") { this.fit(message.width, message.height); this.scheduleSave(); return; }
    if (message.type === "pin" || message.type === "unpin") { await this.editCluster(message); return; }
    if (message.type === "enter" || message.type === "back") {
      await this.navigate(message.type === "back" ? this.graph?.clusterPath.at(-2)?.id ?? null : message.id);
    }
  }

  async reveal(ref: SourceReference): Promise<void> {
    const ticket = this.session.identity.capture();
    if (this.disposed || !ticket.context || ref.sourceRootId !== this.session.sourceRootId) return;
    const version = this.version;
    const { line: _line, ...params } = ref;
    const result = await this.client.request<FileReveal>("view.revealFile", { ...params, hierarchy: true }, ticket.context);
    if (this.disposed || version !== this.version || !this.session.identity.accept(ticket, result, "read")) return;
    await this.navigate(result.clusterId);
    if (!this.disposed && this.session.identity.isCurrent(ticket)) this.select(result.entityId);
  }

  private async navigate(clusterId: string | null): Promise<void> {
    if (this.viewport) this.cameras.set(this.clusterId, this.viewport);
    this.clusterId = clusterId;
    this.viewport = this.cameras.get(clusterId);
    this.selected = null;
    await this.load();
    await this.saveState();
  }

  private scheduleSave(): void {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => { void this.saveState(); }, 150);
  }

  async saveState(): Promise<void> {
    clearTimeout(this.saveTimer);
    if (this.disposed || !this.graph || !this.observed || !this.session.identity.isCurrent(this.observed)) return;
    if (this.viewport) this.cameras.set(this.clusterId, this.viewport);
    const state = { clusterId: this.clusterId,
      cameras: [...this.cameras].slice(-512).map(([clusterId, viewport]) => ({ clusterId, viewport })) };
    const serialized = JSON.stringify(state), ticket = this.observed;
    if (serialized === this.savedState) return;
    try {
      await this.client.request("view.state.set", { view: "file", state }, ticket.context);
      if (this.observed === ticket && this.session.identity.isCurrent(ticket)) this.savedState = serialized;
    } catch (error) { if (!this.disposed) this.log(`File View state: ${viewError(error)}`); }
  }

  private fit(width: number, height: number): void {
    if (!this.graph) return;
    const scale = Math.min(2, Math.max(0.1, Math.min((width - 48) / this.graph.width, (height - 48) / this.graph.height)));
    this.viewport = { scale, x: (width - this.graph.width * scale) / 2 - this.graph.bounds.x * scale,
      y: (height - this.graph.height * scale) / 2 - this.graph.bounds.y * scale };
    this.changed();
  }

  private async load(method = "view.get", params: Record<string, unknown> = { view: "file", clusterId: this.clusterId, hierarchy: true }): Promise<void> {
    const ticket = this.session.identity.capture();
    if (this.disposed || !ticket.context) return;
    const request = ++this.requestNumber;
    const previous = method === "view.get" ? undefined : this.graph;
    this.version++;
    this.loading = true;
    this.graph = undefined;
    this.error = "";
    this.changed();
    const current = () => !this.disposed && request === this.requestNumber && this.session.identity.isCurrent(ticket);
    try {
      const result = await this.client.request<FileViewResponse>(method, params, ticket.context);
      if (current() && this.session.identity.accept(ticket, result, "read")) {
        this.graph = result;
        if (this.clusterId !== result.clusterId) this.viewport = this.cameras.get(result.clusterId);
        this.clusterId = result.clusterId;
        if (this.selected && !result.nodes.some(node => node.id === this.selected)) this.selected = null;
      }
    } catch (error) {
      if (current()) {
        this.graph = previous;
        this.error = error instanceof BackendError && error.code === "model_unavailable"
          ? "Run ICODA: Analyse Project to display its files." : `File View: ${viewError(error)}`;
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
    if (this.loading) return "Loading File View…";
    if (!this.graph) return "Run ICODA: Analyse Project to display its source structure.";
    if (!this.graph.nodes.length) return "No analysed files. Analyse the project or choose another target.";
    if (this.session.data?.modelState === "stale" || this.graph.stale) {
      return `Stale model: ${this.session.data?.staleReason || this.graph.staleReason}`;
    }
    return `${this.graph.nodes.length} visible nodes · Select a cluster to expand; select a file to open source.`;
  }

  dispose(): void { void this.saveState(); this.interactions.dispose(); this.disposed = true; this.requestNumber++; }
}
