import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { createInterface, Interface } from "node:readline";
import {
  BackendError, Initialization, isObject, MAX_REQUEST_BYTES, Notification,
  PROTOCOL_VERSION, readError, SessionContext,
} from "./protocol";

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  cleanup: () => void;
  progress?: (message: string) => void;
}

export interface RequestOptions {
  signal?: AbortSignal;
  progress?: (message: string) => void;
}

export interface BackendOptions {
  python: string;
  packageRoot: string;
  log: (text: string) => void;
  onNotification?: (notification: Notification) => void;
  onExit?: (error: Error) => void;
  onRequest?: (method: string) => void | Promise<void>;
  protocolVersion?: number;
}

/** Own one Python service connection; no VS Code dependency or project-state inference. */
export class BackendClient {
  readonly ready: Promise<Initialization>;
  readonly closed: Promise<void>;
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly lines: Interface;
  private readonly pending = new Map<number, PendingRequest>();
  private nextId = 1;
  private stopped?: Error;
  private killTimer?: NodeJS.Timeout;

  constructor(private readonly options: BackendOptions) {
    this.child = spawn(options.python, ["-m", "icoda_core.service"], {
      cwd: options.packageRoot, stdio: "pipe", shell: false, windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });
    this.lines = createInterface({ input: this.child.stdout.setEncoding("utf8"), crlfDelay: Infinity });
    this.closed = new Promise(resolve => this.child.once("close", () => {
      clearTimeout(this.killTimer);
      this.lines.close();
      this.lines.removeAllListeners();
      this.child.stderr.removeAllListeners("data");
      this.child.removeAllListeners();
      resolve();
    }));
    this.listen();
    this.ready = this.initialize(options.protocolVersion ?? PROTOCOL_VERSION);
  }

  get pid(): number | undefined {
    return this.child.pid;
  }

  get busy(): boolean { return this.pending.size > 0; }

  request<T = unknown>(method: string, params = {}, context?: SessionContext, options: RequestOptions = {}): Promise<T> {
    return Promise.resolve(this.options.onRequest?.(method)).then(() => this.ready)
      .then(() => this.send(method, params, context, options) as Promise<T>);
  }

  private listen(): void {
    this.lines.on("line", line => this.receive(line));
    this.child.stderr.setEncoding("utf8").on("data", text => this.options.log(text));
    this.child.once("error", error => this.stop(new BackendError("backend_exited", `Backend process error: ${error.message}`)));
    this.child.once("exit", (code, signal) => this.stop(new BackendError("backend_exited",
      `Backend exited (${signal ? `signal ${signal}` : `code ${code}`}). Restart Backend to reconnect.`,
      { code, signal },
    )));
    for (const stream of [this.child.stdin, this.child.stdout, this.child.stderr]) {
      stream.on("error", error => this.stop(new BackendError("backend_exited", `Backend stream error: ${error.message}`)));
    }
  }

  private async initialize(version: number): Promise<Initialization> {
    const timer = setTimeout(() => this.stop(new Error("Backend initialization timed out after 10 seconds.")), 10_000);
    try {
      const result = await this.send("initialize", { protocolVersion: version });
      if (!isObject(result) || result.protocolVersion !== version) {
        throw new BackendError("protocol_version_mismatch", "Backend returned an incompatible protocol version.");
      }
      if (!isObject(result.runtime) || typeof result.runtime.python !== "string"
          || typeof result.backendVersion !== "string" || !isObject(result.capabilities)) {
        throw new Error("Invalid backend initialization result.");
      }
      return result as unknown as Initialization;
    } catch (error) {
      this.stop(error instanceof Error ? error : new Error(String(error)));
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  private send(method: string, params: object, context?: SessionContext, options: RequestOptions = {}): Promise<unknown> {
    if (this.stopped) return Promise.reject(this.stopped);
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const frame = JSON.stringify({ ...context, id, method, params }) + "\n";
      if (Buffer.byteLength(frame, "utf8") > MAX_REQUEST_BYTES) {
        reject(new BackendError("message_too_large", "Request exceeds the 1 MiB frame limit."));
        return;
      }
      const cancel = () => { void this.request("operation.cancel", { requestId: id }).catch(error => {
        this.options.log(`Cancellation: ${String(error)}\n`);
      }); };
      const cleanup = () => options.signal?.removeEventListener("abort", cancel);
      this.pending.set(id, { resolve, reject, cleanup, progress: options.progress });
      this.child.stdin.write(frame, "utf8", error => {
        if (error) this.stop(new BackendError("backend_exited", `Backend write failed: ${error.message}`));
      });
      options.signal?.addEventListener("abort", cancel, { once: true });
      if (options.signal?.aborted) cancel();
    });
  }

  private receive(line: string): void {
    if (this.stopped) return;
    try {
      const message: unknown = JSON.parse(line);
      if (!isObject(message)) throw new Error("Backend frame must be an object.");
      if (!("id" in message) && typeof message.method === "string" && isObject(message.params)) {
        if (message.method === "operation.progress" && typeof message.params.requestId === "number"
            && typeof message.params.message === "string") {
          this.pending.get(message.params.requestId)?.progress?.(message.params.message);
        }
        this.options.onNotification?.({ method: message.method, params: message.params });
        return;
      }
      this.respond(message);
    } catch (error) {
      this.stop(new Error(`Invalid backend protocol: ${String(error)}`));
    }
  }

  private respond(message: Record<string, unknown>): void {
    const request = typeof message.id === "number" ? this.pending.get(message.id) : undefined;
    if (!request) throw new Error(`Unexpected response ID: ${String(message.id)}`);
    if (message.status === "ok" && "result" in message) {
      request.resolve(message.result);
    } else if (message.status === "error") {
      request.reject(readError(message.error));
    } else if (message.status === "cancelled") {
      request.reject(new BackendError("cancelled", "Backend request was cancelled."));
    } else {
      throw new Error(`Unexpected response status: ${String(message.status)}`);
    }
    request.cleanup();
    this.pending.delete(message.id as number);
  }

  private stop(error: Error): void {
    if (this.stopped) return;
    this.stopped = error;
    for (const request of this.pending.values()) { request.cleanup(); request.reject(error); }
    this.pending.clear();
    this.lines.removeAllListeners();
    this.lines.close();
    // EOF lets Python cancel and reap its owned trees on Windows as well as POSIX.
    this.child.stdin.end();
    if (this.child.pid && this.child.exitCode === null && this.child.signalCode === null) {
      this.killTimer = setTimeout(() => this.child.kill("SIGKILL"), 7_000);
      this.killTimer.unref();
    }
    this.options.onExit?.(error);
  }

  dispose(): Promise<void> {
    this.stop(new BackendError("backend_disposed", "Backend disposed; outstanding requests were cancelled locally."));
    return this.closed;
  }
}
