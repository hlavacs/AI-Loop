import { FileViewMessage, parseFileViewMessage } from "./fileViewMessages";

export type ClassViewMessage = Exclude<FileViewMessage, { type: "reveal" }>;

/** Classes/members use backend identities only, with the established strict camera schema. */
export function parseClassViewMessage(value: unknown): ClassViewMessage | undefined {
  const message = parseFileViewMessage(value);
  return message?.type === "reveal" ? undefined : message;
}

export function registerClassCommand<T>(register: (name: string, action: () => unknown) => T,
  open: () => unknown): T {
  return register("icoda.openClassView", open);
}
