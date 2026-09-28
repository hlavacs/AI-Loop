import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";

export const targetCommands = [
  { command: "icoda.refreshTargets", title: "Refresh Targets", method: "targets.refresh" },
  { command: "icoda.buildTarget", title: "Build Target", method: "build.run" },
  { command: "icoda.testProject", title: "Run All Project Tests", method: "tests.run" },
  { command: "icoda.runTarget", title: "Run Target", method: "target.run" },
  { command: "icoda.recordTrace", title: "Record Trace", method: "trace.record" },
] as const;

interface CancellationToken {
  readonly isCancellationRequested: boolean;
  onCancellationRequested(listener: () => void): { dispose(): void };
}

/** The native Cancel button aborts only this backend request, using its actual wire ID. */
export async function runTargetOperation(client: Pick<BackendClient, "request">, session: ProjectSession,
  method: string, params: object, token: CancellationToken, progress: (message: string) => void) {
  const controller = new AbortController();
  const listener = token.onCancellationRequested(() => controller.abort());
  if (token.isCancellationRequested) controller.abort();
  try {
    return await session.operate(client, method, params, { signal: controller.signal, progress });
  } finally {
    listener.dispose();
  }
}

export function registerTargetCommands<T>(register: (name: string, action: () => unknown) => T,
  run: (method: string, title: string) => unknown): T[] {
  return targetCommands.map(item => register(item.command, () => run(item.method, item.title)));
}
