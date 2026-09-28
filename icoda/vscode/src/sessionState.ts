import { SessionContext } from "./protocol";

export interface SessionTicket {
  readonly generation: number;
  readonly context?: SessionContext;
}

type Transition = "open" | "read" | "analyse" | "refresh" | "workflow" | { targetId: string | null };

/** Own wire identity and invalidate outstanding replies when a connection/project is replaced. */
export class SessionState {
  private generation = 0;
  private current?: SessionContext;

  constructor(private readonly log: (message: string) => void) {}

  get context(): SessionContext | undefined {
    return this.current && { ...this.current };
  }

  capture(): SessionTicket {
    return { generation: this.generation, context: this.context };
  }

  reset(): void {
    this.invalidate();
    this.current = undefined;
  }

  invalidate(): void {
    this.generation++;
  }

  isCurrent(ticket: SessionTicket): boolean {
    return ticket.generation === this.generation && sameContext(ticket.context, this.current);
  }

  accept(ticket: SessionTicket, response: SessionContext, transition: Transition): boolean {
    if (!this.isCurrent(ticket) || !validTransition(ticket.context, response, transition)) {
      this.log(`Dropped stale response: sessionId=${response.sessionId}, modelRevision=${response.modelRevision}, targetId=${response.targetId}`);
      return false;
    }
    const { sessionId, modelRevision, targetId } = response;
    this.current = { sessionId, modelRevision, targetId };
    return true;
  }
}

export function sameContext(left?: SessionContext, right?: SessionContext): boolean {
  return left?.sessionId === right?.sessionId && left?.modelRevision === right?.modelRevision
    && left?.targetId === right?.targetId;
}

/** v1 reads retain identity; analysis advances once; selection advances only on change. */
function validTransition(before: SessionContext | undefined, after: SessionContext, change: Transition): boolean {
  if (change === "open") return Boolean(after.sessionId) && after.modelRevision === 1;
  if (!before || before.sessionId !== after.sessionId) return false;
  if (change === "read") return sameContext(before, after);
  if (change === "workflow") return after.modelRevision === before.modelRevision + 1 && after.targetId === before.targetId;
  if (change === "analyse" || change === "refresh") return after.modelRevision === before.modelRevision + 1;
  const revision = before.modelRevision + Number(change.targetId !== before.targetId);
  return after.modelRevision === revision && after.targetId === change.targetId;
}
