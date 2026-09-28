import { dirname, extname, isAbsolute, relative, resolve, sep } from "node:path";
import { realpath } from "node:fs/promises";
import { ProjectSession } from "./projectSession";
import { SessionTicket } from "./sessionState";

// Keep aligned with analysis.CPP_SUFFIXES and the Python AST frontend.
const analysedExtensions = new Set([
  ".py", ".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".h++", ".inl",
  ".cppm", ".ixx", ".mpp", ".cxxm", ".c++m", ".ccm",
]);

/** Lexical boundary check; the service and editor also check resolved symlink paths. */
export function projectFile(root: string, file: string): string | undefined {
  if (!file || file.includes("\0")) return undefined;
  const path = relative(root, resolve(root, file));
  const parts = path.split(sep);
  if (!path || isAbsolute(path) || parts[0] === ".." || parts.some(part => [".git", ".icoda"].includes(part))) {
    return undefined;
  }
  return parts.join("/");
}

export function analysedFile(root: string, file: string): string | undefined {
  return analysedExtensions.has(extname(file).toLowerCase()) ? projectFile(root, file) : undefined;
}

/** Resolve the root once and each save before comparing; aliases use the same boundary. */
export function watchSourcePaths(root: string, mark: (file: string) => void, log: (message: string) => void) {
  let disposed = false;
  const ready = realpath(root).then(path => new SourceChanges(path, mark)).catch(error => {
    log(`Could not check project source root: ${String(error)}`);
    return undefined;
  });
  return {
    async saved(file: string, deleted = false): Promise<void> {
      if (disposed || !analysedExtensions.has(extname(file).toLowerCase())) return;
      try {
        // Deleted files have no realpath; resolve their closest surviving parent to exclude symlink escapes.
        const [changes, path] = await Promise.all([ready, deleted ? deletedPath(file) : realpath(file)]);
        if (!disposed) changes?.saved(path);
      } catch (error) {
        log(`Could not check saved source ${file}: ${String(error)}`);
      }
    },
    dispose(): void {
      disposed = true;
      void ready.then(changes => changes?.dispose());
    },
  };
}

async function deletedPath(file: string): Promise<string> {
  try { return await realpath(file); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT" || dirname(file) === file) throw error;
    const parent = dirname(file);
    return resolve(await deletedPath(parent), relative(parent, file));
  }
}

/** Retry only deferred refreshes; tickets prevent an old edit from analysing a new selection. */
export class AutomaticAnalysis {
  private pending?: SessionTicket;
  private timer?: ReturnType<typeof setTimeout>;
  private running = false;
  private disposed = false;

  constructor(private readonly session: ProjectSession, private readonly analyse: () => Promise<boolean>,
    private readonly log: (message: string) => void) {}

  changed(): void {
    if (this.disposed) return;
    this.pending = this.session.identity.capture();
    this.schedule();
  }

  private schedule(): void {
    clearTimeout(this.timer);
    if (!this.disposed && this.pending) this.timer = setTimeout(() => { void this.flush(); }, 300);
  }

  private async flush(): Promise<void> {
    if (this.disposed || this.running || !this.pending) return;
    const ticket = this.pending;
    this.pending = undefined;
    if (!ticket.context || !this.session.identity.isCurrent(ticket)) return;
    this.running = true;
    try {
      const completed = await this.analyse();
      const now = this.session.identity.capture();
      if (!completed && this.session.identity.isCurrent(ticket)) this.pending ??= ticket;
      // A save during our own analysis needs one more pass against its newly published revision.
      if (completed && this.pending?.generation === ticket.generation && now.generation === ticket.generation
          && now.context?.sessionId === ticket.context.sessionId && now.context?.targetId === ticket.context.targetId
          && now.context?.modelRevision === ticket.context.modelRevision + 1) this.pending = now;
    } catch (error) { if (!this.disposed) this.log(`Automatic analysis: ${String(error)}`); }
    finally { this.running = false; this.schedule(); }
  }

  dispose(): void { this.disposed = true; this.pending = undefined; clearTimeout(this.timer); }
}

/** One trailing notification per burst of project saves, cancelled on disposal. */
export class SourceChanges {
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;

  constructor(private readonly root: string, private readonly mark: (file: string) => void,
    private readonly delay = 1000) {}

  saved(file: string): void {
    const relative = analysedFile(this.root, file);
    if (this.disposed || !relative) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = undefined;
      this.mark(relative);
    }, this.delay);
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.timer);
    this.timer = undefined;
  }
}
