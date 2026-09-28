import { GraphOptions } from "./graphInteractions";
import { isObject } from "./protocol";
import { TraceAction } from "./tracePlayback";

export interface Viewport { x: number; y: number; scale: number }

type Action = GraphOptions | { type: "select"; usr: string }
  | { type: "traceLoad" }
  | { type: "traceStep"; action: TraceAction }
  | { type: "traceReset" }
  | { type: "traceSeek"; usr: string }
  | { type: "root"; usr: string | null }
  | { type: "viewport"; viewport: Viewport }
  | { type: "depth"; depth: number }
  | { type: "callers"; callers: boolean }
  | { type: "filter"; text: string }
  | { type: "fit"; width: number; height: number };
export type CallViewMessage = { type: "ready" } | (Action & { version: number });

const MAX_MESSAGE_BYTES = 16 * 1024;

export function registerTraceCommands<T>(register: (name: string, action: () => Promise<void>) => T,
  navigate: (action: TraceAction | "reset") => Promise<void>): T[] {
  return (["previous", "over", "into", "out", "reset"] as const).map(action =>
    register(`icoda.trace${action[0]!.toUpperCase()}${action.slice(1)}`, () => navigate(action)));
}

/** No VS Code dependency: every message crosses this boundary before dispatch. */
export function parseCallViewMessage(value: unknown): CallViewMessage | undefined {
  if (!isObject(value) || !bounded(value)) return undefined;
  if (value.type === "ready") return fields(value, ["type"]) ? { type: "ready" } : undefined;
  if (!Number.isSafeInteger(value.version) || (value.version as number) < 0) return undefined;
  const valid = validAction(value);
  return valid ? value as CallViewMessage : undefined;
}

function bounded(value: object): boolean {
  try { return Buffer.byteLength(JSON.stringify(value), "utf8") <= MAX_MESSAGE_BYTES; }
  catch { return false; }
}

function fields(value: Record<string, unknown>, names: string[]): boolean {
  return Object.keys(value).length === names.length && names.every(name => Object.prototype.hasOwnProperty.call(value, name));
}

function usr(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= 4096 && !value.includes("\0");
}

function finite(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function validViewport(value: unknown): value is Viewport {
  return isObject(value) && fields(value, ["x", "y", "scale"])
    && finite(value.x, -1e7, 1e7) && finite(value.y, -1e7, 1e7) && finite(value.scale, 0.1, 4);
}

function validAction(value: Record<string, unknown>): boolean {
  const has = (...names: string[]) => fields(value, ["type", "version", ...names]);
  switch (value.type) {
    case "select": return has("usr") && usr(value.usr);
    case "traceLoad": case "traceReset": return has();
    case "traceStep": return has("action") && ["previous", "over", "into", "out"].includes(value.action as string);
    case "traceSeek": return has("usr") && usr(value.usr);
    case "root": return has("usr") && (value.usr === null || usr(value.usr));
    case "viewport": return has("viewport") && validViewport(value.viewport);
    case "depth": return has("depth") && Number.isInteger(value.depth) && finite(value.depth, 0, 12);
    case "callers": return has("callers") && typeof value.callers === "boolean";
    case "graphOptions": return has("text", "depth") && typeof value.text === "string"
      && value.text.length <= 256 && !value.text.includes("\0")
      && Number.isInteger(value.depth) && finite(value.depth, 0, 12);
    case "filter": return has("text") && typeof value.text === "string"
      && value.text.length <= 256 && !value.text.includes("\0");
    case "fit": return has("width", "height") && finite(value.width, 1, 100_000) && finite(value.height, 1, 100_000);
    default: return false;
  }
}
