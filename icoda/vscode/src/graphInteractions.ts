import { BackendClient } from "./backendClient";
import { SessionContext } from "./protocol";
import { ProjectSession } from "./projectSession";
import { viewError } from "./viewErrors";

export type GraphOptions = { type: "graphOptions"; text: string; depth: number };
export interface GraphDecisions { [id: string]: { hidden: boolean; dimmed: boolean } }
interface GraphIdentity extends SessionContext { sourceRootId: string }

/** Shared request routing only: Python owns matching, aggregate identities and graph traversal. */
export class GraphInteractions {
  text = "";
  depth = 0;
  private decisions: GraphDecisions = {};
  private graph?: GraphIdentity;
  private selected: string | null = null;
  private focus: string | null = null;
  private traceId?: string;
  private request = 0;
  private disposed = false;
  private pending = false;
  private error = "";

  constructor(private readonly session: ProjectSession, private readonly client: Pick<BackendClient, "request">,
    private readonly changed: () => void, private readonly log: (message: string) => void) {}

  async control(options: GraphOptions): Promise<void> {
    this.text = options.text;
    this.depth = options.depth;
    this.focus = this.depth ? this.selected : null;
    await this.refresh();
  }

  snapshot(graph: GraphIdentity | undefined, selected: string | null, traceId?: string) {
    this.selected = selected;
    const focus = this.depth ? selected : null;
    if (this.graph !== graph || this.focus !== focus || this.traceId !== traceId) {
      this.graph = graph; this.focus = focus; this.traceId = traceId;
      void this.refresh();
    }
    return { text: this.text, depth: this.depth, decisions: this.decisions, pending: this.pending, error: this.error };
  }

  private async refresh(): Promise<void> {
    const request = ++this.request, graph = this.graph;
    const ticket = this.session.identity.capture();
    this.decisions = {}; this.error = ""; this.pending = false;
    if (this.disposed || !graph || !ticket.context || (!this.text.trim() && !this.depth)) return;
    this.pending = true;
    const current = () => !this.disposed && request === this.request && this.session.identity.isCurrent(ticket);
    try {
      const result = await this.client.request<GraphIdentity & { decisions: GraphDecisions }>("graph.interactions",
        { sourceRootId: graph.sourceRootId, text: this.text, depth: this.depth, focus: this.focus,
          ...(this.traceId ? { traceId: this.traceId } : {}) }, ticket.context);
      if (current() && result.sourceRootId === graph.sourceRootId && this.session.identity.accept(ticket, result, "read")) {
        this.decisions = result.decisions;
      }
    } catch (error) {
      if (current()) { this.error = `Graph filter: ${viewError(error)}`; this.log(this.error); }
    } finally {
      if (current()) { this.pending = false; this.changed(); }
    }
  }

  dispose(): void { this.disposed = true; this.request++; }
}

/** A compact, keyboard-accessible popover; never adds a permanent toolbar row. */
export function graphInteractionControls(): string {
  return `<details id="graphOptions"><summary>Focus</summary><div class="graph-options">
<label>Graph filter <input id="graphQuery" type="search" maxlength="256" placeholder="namespace:app::* edge:calls"
 title="Name substring or name:, kind:, status:, covered:, stale:, cluster:, namespace:, edge:. namespace:app is exact; namespace:app::* includes descendants. Expandable groups, Call roots and the selection stay visible."></label>
<label>Neighborhood <input id="graphNeighborhood" type="number" min="0" max="12" value="0"
 title="Relationship hops from the selected source node; 0 disables dimming. File/class nodes include their entities."></label>
<button id="graphClear">Clear</button><span id="graphFeedback" role="status" aria-live="polite"></span>
</div></details>`;
}
