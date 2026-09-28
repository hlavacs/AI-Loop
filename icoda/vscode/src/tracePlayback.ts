import { realpath } from "node:fs/promises";
import { isAbsolute, relative, sep } from "node:path";
import { BackendError, SessionContext, SourceReference } from "./protocol";

export type TraceAction = "previous" | "over" | "into" | "out";
export interface PlaybackState extends SessionContext {
  sourceRootId: string; traceId: string; position: number; total: number;
  currentEntityUsr: string | null;
  source: { sourceRootId: string; file: string | null; line: number } | null;
  currentCall: { usr: string; source: PlaybackState["source"]; threadId: string; depth: number; sequence: number } | null;
  repeatCount: number; callerCounts: Record<string, number>; status: string;
  availability: Record<TraceAction | "reset", boolean>;
}

export function playbackSource(state: PlaybackState): SourceReference | undefined {
  return state.currentEntityUsr && state.source
    ? { sourceRootId: state.source.sourceRootId, usr: state.currentEntityUsr, line: state.source.line } : undefined;
}

/** Native pickers cannot lock a directory; enforce its physical boundary after selection. */
export async function projectTracePath(root: string, file: string): Promise<string> {
  const [project, path] = await Promise.all([realpath(root), realpath(file)]);
  const local = relative(project, path);
  if (!local || isAbsolute(local) || local.split(sep)[0] === "..") {
    throw new BackendError("invalid_trace", "Choose a trace inside the selected project's workspace.");
  }
  return path;
}
