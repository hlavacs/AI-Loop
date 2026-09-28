/** Idle scheduling only; the service owns provider, analysis and pending-candidate gates. */
export class BackgroundPurposeComments {
  private timer?: ReturnType<typeof setTimeout>;
  private key?: string;
  private attempted?: string;
  private active?: { abort: AbortController; done: Promise<boolean> };
  private disposed = false;

  constructor(private readonly state: () => { key?: string; enabled: boolean; eligible: boolean },
    private readonly run: (signal: AbortSignal) => Promise<boolean>, private readonly log: (message: string) => void,
    private readonly delay = 30_000) {}

  sync(): void {
    const state = this.state();
    if (state.key !== this.key) {
      this.active?.abort.abort();
      this.attempted = undefined;
      this.key = state.key;
    }
    if (!state.enabled) this.active?.abort.abort();
    this.activity();
  }

  activity(): void {
    clearTimeout(this.timer);
    const { enabled, key } = this.state();
    if (!this.disposed && enabled && key && this.attempted !== key) {
      this.timer = setTimeout(() => { void this.flush(); }, this.delay);
    }
  }

  /** Only cancel the job this timer owns; foreground workflows have separate state. */
  async stop(): Promise<void> {
    clearTimeout(this.timer);
    this.active?.abort.abort();
    await this.active?.done.catch(() => {});
  }

  private async flush(): Promise<void> {
    const { key, enabled, eligible } = this.state();
    if (this.disposed || !enabled || !key || this.attempted === key) return;
    if (!eligible || this.active) { this.activity(); return; }
    const abort = new AbortController();
    const active = { abort, done: this.run(abort.signal) };
    this.active = active;
    try {
      // One attempt per analysed revision prevents unattended provider retry loops.
      if (await active.done && this.key === key) this.attempted = key;
    } catch (error) {
      if (this.key === key) this.attempted = key;
      if (!abort.signal.aborted && !this.disposed) this.log(`Background purpose comments: ${String(error)}`);
    }
    finally { if (this.active === active) this.active = undefined; this.activity(); }
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.timer);
    this.active?.abort.abort();
  }
}
