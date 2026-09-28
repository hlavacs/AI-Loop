import { BackendClient } from "./backendClient";
import { SessionContext } from "./protocol";
import { ProjectSession } from "./projectSession";
import { SessionTicket } from "./sessionState";
import { viewError } from "./viewErrors";

/** Coalesce camera writes and bind them to the project/target that produced them. */
export class ViewState<T extends object> {
  private ticket?: SessionTicket;
  private timer?: ReturnType<typeof setTimeout>;
  private pending?: T;
  private saved = "";
  private disposed = false;
  private writable = false;
  private writing: Promise<void> = Promise.resolve();

  constructor(private readonly view: "call" | "class" | "mindmap", private readonly session: ProjectSession,
    private readonly client: Pick<BackendClient, "request">, private readonly log: (message: string) => void) {}

  get bound(): boolean { return Boolean(this.ticket && this.current(this.ticket)); }

  async restore(): Promise<T | undefined> {
    clearTimeout(this.timer);
    this.pending = undefined;
    this.writable = false;
    const ticket = this.ticket = this.session.identity.capture();
    if (this.disposed || !ticket.context) return undefined;
    try {
      const result = await this.client.request<SessionContext & { state: T }>("view.state.get", { view: this.view }, ticket.context);
      if (!this.current(ticket) || !this.session.identity.accept(ticket, result, "read")) return undefined;
      this.saved = JSON.stringify(result.state);
      this.writable = true;
      return result.state;
    } catch (error) {
      if (this.current(ticket)) this.log(`${this.view} view state: ${viewError(error)}`);
      // A corrupt/unreadable state must not be silently replaced by defaults on the next pan.
      return undefined;
    }
  }

  schedule(state: T): void {
    if (!this.ticket || !this.current(this.ticket) || !this.writable) return;
    this.pending = structuredClone(state);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { void this.flush(); }, 150);
  }

  async flush(): Promise<void> {
    clearTimeout(this.timer);
    const state = this.pending, ticket = this.ticket;
    this.pending = undefined;
    if (state && ticket && this.current(ticket) && this.writable) {
      const serialized = JSON.stringify(state);
      this.writing = this.writing.then(async () => {
        if (!this.session.identity.isCurrent(ticket) || serialized === this.saved) return;
        try {
          await this.client.request("view.state.set", { view: this.view, state }, ticket.context);
          if (this.current(ticket)) this.saved = serialized;
        } catch (error) { this.log(`${this.view} view state: ${viewError(error)}`); }
      });
    }
    await this.writing;
  }

  private current(ticket: SessionTicket): boolean {
    return !this.disposed && this.ticket === ticket && this.session.identity.isCurrent(ticket);
  }

  dispose(): void { void this.flush(); this.disposed = true; clearTimeout(this.timer); }
}
