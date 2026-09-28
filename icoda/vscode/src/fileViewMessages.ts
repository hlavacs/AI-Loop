import { GraphOptions } from "./graphInteractions";
import { isObject } from "./protocol";
import { Viewport, parseCallViewMessage } from "./callViewMessages";

export type FileViewMessage = { type: "ready" }
  | ({ version: number } & (GraphOptions |
    { type: "enter"; id: string } | { type: "select"; id: string } | { type: "back" } | { type: "reveal" }
    | { type: "pin" | "unpin" | "rename" | "assign"; id: string }
    | { type: "viewport"; viewport: Viewport } | { type: "fit"; width: number; height: number }));

/** Reuse the established bounded camera validation; file actions have their own strict schema. */
export function parseFileViewMessage(value: unknown): FileViewMessage | undefined {
  if (!isObject(value)) return undefined;
  if (["ready", "viewport", "fit", "graphOptions"].includes(value.type as string)) {
    return parseCallViewMessage(value) ? value as FileViewMessage : undefined;
  }
  if (!Number.isSafeInteger(value.version) || (value.version as number) < 0) return undefined;
  const keys = Object.keys(value).sort().join(",");
  if (["back", "reveal"].includes(value.type as string) && keys === "type,version") return value as FileViewMessage;
  if (!["enter", "select", "pin", "unpin", "rename", "assign"].includes(value.type as string) || keys !== "id,type,version") return undefined;
  if (["pin", "unpin", "rename"].includes(value.type as string)
      && (typeof value.id !== "string" || !value.id.startsWith("cluster:") || !value.id.slice(8).trim())) return undefined;
  // Select validation also bounds UTF-8 bytes, nonempty IDs, length and NULs.
  return parseCallViewMessage({ type: "select", version: value.version, usr: value.id })
    ? value as FileViewMessage : undefined;
}

export function registerFileCommands<T>(register: (name: string, action: () => unknown) => T,
  open: () => unknown, reveal: () => unknown, assign: () => unknown): T[] {
  return [register("icoda.openFileView", open), register("icoda.revealInFileView", reveal),
    register("icoda.assignFileCluster", assign)];
}
