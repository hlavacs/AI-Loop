import { GraphOptions } from "./graphInteractions";
import { isObject } from "./protocol";
import { Viewport, parseCallViewMessage } from "./callViewMessages";

export type MindMapMessage = { type: "ready" }
  | ({ version: number } & (GraphOptions |
    { type: "select" | "openStep"; nodeId: string } | { type: "setExpanded"; nodeId: string; expanded: boolean }
    | { type: "viewport"; viewport: Viewport } | { type: "fit"; width: number; height: number }));

/** Accept only bounded identities, booleans and the established strict camera schema. */
export function parseMindMapMessage(value: unknown): MindMapMessage | undefined {
  if (!isObject(value)) return undefined;
  if (["ready", "viewport", "fit", "graphOptions"].includes(value.type as string)) {
    return parseCallViewMessage(value) ? value as MindMapMessage : undefined;
  }
  const keys = Object.keys(value).sort().join(",");
  const selection = ["select", "openStep"].includes(value.type as string) && keys === "nodeId,type,version";
  const expansion = value.type === "setExpanded" && keys === "expanded,nodeId,type,version"
    && typeof value.expanded === "boolean";
  if (!selection && !expansion) return undefined;
  if (typeof value.nodeId !== "string" || Buffer.from(value.nodeId, "utf8").toString("utf8") !== value.nodeId) return undefined;
  return parseCallViewMessage({ type: "select", usr: value.nodeId, version: value.version })
    ? value as MindMapMessage : undefined;
}

export function registerMindMapCommand<T>(register: (name: string, action: () => unknown) => T,
  open: () => unknown): T {
  return register("icoda.openMindMap", open);
}
