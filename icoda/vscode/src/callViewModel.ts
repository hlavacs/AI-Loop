import { ViewState } from "./viewState";
import { GraphInteractions } from "./graphInteractions";
import { viewError } from "./viewErrors";
import { BackendClient } from "./backendClient";
import { BackendError, SessionContext, SourceReference } from "./protocol";
import { ProjectSession } from "./projectSession";
import { sameContext } from "./sessionState";
import { CallViewMessage, Viewport } from "./callViewMessages";
import { PlaybackState, TraceAction, playbackSource } from "./tracePlayback";

export interface CallNode {
  usr: string; label: string; x: number; y: number; level: number;
  kind: string; status: string; signature: string; brief: string;
  sourceRootId: string; file: string | null; line: number | null;
  added?: boolean; changed?: boolean;
}

export interface CallEdge {
  source: string; target: string; label: string; kind: "calls";
  loop: boolean; uncertain: boolean; free: boolean;
}

export interface CallViewResponse extends SessionContext {
  sourceRootId: string; view: "call"; root: string | null; roots: string[];
  depth: number; callers?: boolean; libraryMode: boolean;
  nodes: CallNode[]; edges: CallEdge[]; width: number; height: number;
  stale: boolean; staleReason: string;
}

export type CallViewState = Pick<CallViewModel, "graph" | "selected" | "viewport" | "root" | "depth"
  | "callers" | "filter" | "trace" | "version"> & { context: SessionContext };

/** Map presentation only. Coordinates, layers, roots and edge identities belong to Python. */
export function callViewRenderData(view: CallViewResponse, selected: string | null = null, trace?: PlaybackState) {
  const roots = new Set(view.roots);
  return {
    root: view.root, roots: view.roots, libraryMode: view.libraryMode,
    width: view.width, height: view.height,
    nodes: view.nodes.map(node => ({ ...node, selected: node.usr === selected, root: roots.has(node.usr),
      tooltip: `${node.label}\n${node.kind} · ${node.status}\n${node.file ?? "No project source"}:${node.line ?? "—"}`
        + (node.signature ? `\n${node.signature}` : "") + (node.brief ? `\n${node.brief}` : ""),
      change: node.added ? "added" : node.changed ? "changed" : "",
    })),
    edges: view.edges.map(edge => trace
      ? { ...edge, repeatCount: edge.target === trace.currentEntityUsr ? trace.callerCounts[edge.source] ?? 0 : 0 }
      : edge),
  };
}

/** Session-owned graph, controls and viewport survive webview visibility changes. */
export class CallViewModel {
  readonly interactions = new GraphInteractions(this.session, this.client, this.changed, this.log);
  graph?: CallViewResponse;
  selected: string | null = null;
  viewport?: Viewport;
  root: string | null = null;
  depth = 3;
  callers = false;
  // Retain the saved-state field while using the shared filter as the only source of truth.
  get filter(): string { return this.interactions.text; }
  set filter(value: string) { this.interactions.text = value; }
  version = 0;
  loading = false;
  error = "";
  trace?: PlaybackState;
  private readonly persistence = new ViewState<{ root: string | null; depth: number; callers: boolean; filter: string; viewport: Viewport | null }>(
    "call", this.session, this.client, this.log);
  private observed?: SessionContext;
  private requestNumber = 0;
  private traceRequest = 0;
  private disposed = false;

  constructor(private readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly log: (message: string) => void, private readonly changed: () => void,
    private readonly candidateSourceRoot?: string) {
    const saved = candidateSourceRoot ? undefined : session.callViewState;
    if (!candidateSourceRoot) session.callViewState = undefined;
    if (saved && sameContext(saved.context, session.identity.context)) {
      const { context, ...state } = structuredClone(saved);
      Object.assign(this, state);
      this.observed = context;
      this.version++;
      void this.persistence.restore();
    }
  }

  async sync(): Promise<void> {
    const context = this.session.identity.context;
    if (this.disposed || !context) return;
    if (sameContext(context, this.observed)) {
      if (!this.candidateSourceRoot && !this.persistence.bound) await this.persistence.restore();
      if (!this.disposed) this.changed();
      return;
    }
    if (context.targetId !== this.observed?.targetId) {
      this.root = this.selected = null;
      this.viewport = undefined;
    }
    const restore = !this.observed || context.targetId !== this.observed.targetId;
    this.observed = context;
    if (this.trace) this.selected = null;
    this.trace = undefined;
    this.traceRequest++;
    this.graph = undefined;
    this.loading = true;
    this.version++;
    this.changed();
    if (!this.candidateSourceRoot) {
      const ticket = this.session.identity.capture();
      const state = await this.persistence.restore();
      if (this.disposed || !this.session.identity.isCurrent(ticket)) return;
      if (restore && state) { Object.assign(this, state); this.viewport = state.viewport ?? undefined; }
    }
    await this.load();
  }

  /** Selection never changes the root, requests layout, or alters the viewport. */
  select(usr: string): SourceReference | undefined {
    const node = this.graph?.nodes.find(node => node.usr === usr);
    if (!node) return undefined;
    this.selected = usr;
    this.changed();
    return node.kind === "external" ? undefined : { sourceRootId: node.sourceRootId, usr };
  }

  accepts(message: CallViewMessage): boolean {
    if (this.disposed) return false;
    if (message.type === "ready") return true;
    if (this.candidateSourceRoot && message.type.startsWith("trace")) return false;
    if (message.version !== this.version || !this.graph || !sameContext(this.observed, this.session.identity.context)) return false;
    if (message.type === "select" || message.type === "traceSeek" || (message.type === "root" && message.usr !== null)) {
      return this.graph.nodes.some(node => node.usr === message.usr && (message.type === "select" || node.kind !== "external"));
    }
    return true;
  }

  async control(message: Exclude<CallViewMessage, { type: "ready" | "select" | "traceLoad" | "traceStep" | "traceReset" | "traceSeek" }>): Promise<void> {
    if (!this.accepts(message)) return;
    if (message.type === "graphOptions" || message.type === "filter") {
      // Older webviews may still send the former quick-filter message.
      const options = message.type === "filter"
        ? { type: "graphOptions" as const, text: message.text, depth: this.interactions.depth } : message;
      await this.interactions.control(options); this.persist(); this.changed(); return;
    }
    if (message.type === "viewport") { this.viewport = message.viewport; this.persist(); return; }
    if (message.type === "fit") { this.fit(message.width, message.height); this.persist(); return; }
    if (message.type === "root") this.root = message.usr;
    if (message.type === "depth") this.depth = message.depth;
    if (message.type === "callers") this.callers = message.callers;
    await this.load();
    this.persist();
    await this.saveState();
  }

  private persist(): void {
    if (!this.candidateSourceRoot) this.persistence.schedule({ root: this.root, depth: this.depth,
      callers: this.callers, filter: this.filter, viewport: this.viewport ?? null });
  }

  async saveState(): Promise<void> { await this.persistence.flush(); }

  render() {
    const choices = this.graph?.nodes.filter(node => node.kind !== "external")
      .map(node => ({ usr: node.usr, label: node.label })) ?? [];
    return { interactions: this.interactions.snapshot(this.graph, this.selected, this.trace?.traceId),
      type: "render", version: this.version, loading: this.loading,
      graph: this.graph ? callViewRenderData(this.graph, this.selected, this.trace) : undefined,
      selected: this.selected, viewport: this.viewport, root: this.root, choices,
      trace: this.trace, proposal: Boolean(this.candidateSourceRoot),
      depth: this.depth, callers: this.callers, filter: this.filter, message: this.status(),
    };
  }

  dispose(): void {
    if (this.disposed) return;
    if (!this.candidateSourceRoot && this.graph && !this.loading && sameContext(this.observed, this.session.identity.context)) {
      this.session.callViewState = structuredClone({ context: this.observed!, graph: this.graph,
        selected: this.selected, viewport: this.viewport, root: this.root, depth: this.depth,
        callers: this.callers, filter: this.filter, trace: this.trace, version: this.version });
    }
    this.persistence.dispose();
    this.interactions.dispose(); this.disposed = true; this.requestNumber++; this.traceRequest++;
  }

  async loadTrace(path: string, version: number): Promise<void> {
    const result = await this.requestTrace("trace.load", { path }, version);
    if (result) await this.load();
  }

  async navigateTrace(action: TraceAction | "reset" | "seek", version: number, usr?: string): Promise<SourceReference | undefined> {
    if (!this.trace || (action !== "seek" && !this.trace.availability[action])) return undefined;
    const params = { traceId: this.trace.traceId, ...(action === "reset" ? {} : { action }), ...(usr ? { usr } : {}) };
    const result = await this.requestTrace(action === "reset" ? "trace.reset" : "trace.step", params, version);
    return result && playbackSource(result);
  }

  private async requestTrace(method: string, params: Record<string, unknown>, version: number): Promise<PlaybackState | undefined> {
    const ticket = this.session.identity.capture();
    if (!ticket.context || !this.accepts({ type: "traceLoad", version })) return undefined;
    const request = ++this.traceRequest;
    const current = () => !this.disposed && request === this.traceRequest && version === this.version
      && this.session.identity.isCurrent(ticket);
    try {
      const result = await this.client.request<PlaybackState>(method, params, ticket.context);
      if (!current() || !this.session.identity.accept(ticket, result, "read")) return undefined;
      if (method !== "trace.load" && result.traceId !== this.trace?.traceId) return undefined;
      this.trace = result;
      this.selected = result.currentEntityUsr;
      this.error = "";
      this.changed();
      return result;
    } catch (error) {
      if (current()) {
        this.error = `Trace playback: ${viewError(error)}`;
        this.log(this.error);
        this.changed();
      }
      return undefined;
    }
  }

  private status(): string {
    if (!this.session.identity.context) return "Open a workspace folder, then run ICODA: Open Project.";
    if (this.error) return this.error;
    if (this.loading) return "Loading Call View…";
    if (!this.graph) return "Run ICODA: Analyse Project to display its source structure.";
    if (!this.graph.nodes.length) return "No callable entities. Analyse the project or choose another target.";
    if (this.session.data?.modelState === "analysing") return "Analysing project…";
    if (this.session.data?.modelState === "stale" || this.graph.stale) {
      return `Stale model: ${this.session.data?.staleReason || this.graph.staleReason}`;
    }
    return `${this.candidateSourceRoot ? "Proposal · added/changed outlines · " : ""}${this.graph.nodes.length} nodes · dashed ? = uncertain · loop = recursion/backward call`;
  }

  private fit(width: number, height: number): void {
    if (!this.graph) return;
    const scale = Math.min(2, Math.max(0.1, Math.min((width - 48) / this.graph.width, (height - 48) / this.graph.height)));
    this.viewport = { scale, x: (width - this.graph.width * scale) / 2, y: (height - this.graph.height * scale) / 2 };
    this.changed();
  }

  private async load(): Promise<void> {
    const ticket = this.session.identity.capture();
    if (this.disposed || !ticket.context) return;
    const request = ++this.requestNumber;
    this.version++;
    this.graph = undefined;
    this.loading = true;
    this.error = "";
    this.changed();
    try {
      const params = { view: "call", root: this.root, depth: this.depth, callers: this.callers,
        ...(this.candidateSourceRoot ? { sourceRootId: this.candidateSourceRoot } : {}),
        ...(this.trace ? { traceId: this.trace.traceId } : {}) };
      const result = await this.client.request<CallViewResponse>("view.get", params, ticket.context);
      if (this.disposed || request !== this.requestNumber || !this.session.identity.accept(ticket, result, "read")) return;
      this.graph = result;
      if (!result.nodes.some(node => node.usr === this.selected)) this.selected = null;
    } catch (error) {
      if (this.disposed || request !== this.requestNumber || !this.session.identity.isCurrent(ticket)) return;
      if (error instanceof BackendError && error.code === "unknown_root" && this.root !== null) {
        this.log("Call View root is no longer in this model; restoring its entry points.");
        this.root = null;
        await this.load();
        return;
      }
      this.error = error instanceof BackendError && error.code === "model_unavailable"
        ? "Run ICODA: Analyse Project to display its calls." : `Call View: ${viewError(error)}`;
      this.log(this.error);
    } finally {
      if (!this.disposed && request === this.requestNumber && this.session.identity.isCurrent(ticket)) {
        this.loading = false;
        this.changed();
      }
    }
  }
}
