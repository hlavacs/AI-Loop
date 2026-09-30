import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

/** Minimal DOM for executing the shipped script's layout and event handlers; no browser geometry claim. */
export class TestElement {
  children: TestElement[] = [];
  parent?: TestElement;
  hidden = false;
  disabled = false;
  clientWidth = 1000;
  clientHeight = 700;
  width = 100;
  textContent = "";
  attributes = new Map<string, string>();
  listeners = new Map<string, Function>();
  classList = { toggle() {}, add() {}, remove() {} };
  constructor(readonly id: string, readonly document: { activeElement?: TestElement }) {}
  append(...items: TestElement[]): void {
    for (const item of items) {
      if (item.parent) item.parent.children = item.parent.children.filter(child => child !== item);
      item.parent = this;
      this.children.push(item);
    }
  }
  replaceChildren(...items: TestElement[]): void { this.children = []; this.append(...items); }
  add(item: TestElement): void { this.append(item); }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  getAttribute(key: string): string | undefined { return this.attributes.get(key); }
  removeAttribute(key: string): void { this.attributes.delete(key); }
  getBoundingClientRect() { return { width: this.width }; }
  focus(): void { this.document.activeElement = this; }
  contains(item?: TestElement): boolean { return this === item || this.children.some(child => child.contains(item)); }
  addEventListener(type: string, action: Function): void { this.listeners.set(type, action); }
  emit(type: string, event: Record<string, unknown> = {}): void {
    this.listeners.get(type)?.({ preventDefault() {}, stopPropagation() {}, target: this, ...event });
  }
  querySelectorAll(selector: string): TestElement[] {
    if (selector === "button:not(:disabled)") return this.children.filter(child => !child.disabled);
    return [];
  }
  querySelector(selector: string): TestElement | undefined { return this.querySelectorAll(selector)[0]; }
  closest(selector: string): TestElement | undefined { return selector === "button:not(:disabled)" && !this.disabled ? this : undefined; }
}

export function callWebview() {
  const elements = new Map<string, TestElement>(), messages: Record<string, unknown>[] = [];
  const document = { activeElement: undefined as TestElement | undefined,
    getElementById: (id: string) => elements.get(id),
    createElementNS: (_namespace: string, name: string) => new TestElement(name, document),
    addEventListener() {}, fonts: { ready: Promise.resolve() },
  };
  for (const id of ["graph", "scene", "root", "depth", "callers", "graphQuery", "fit", "zoomIn", "zoomOut", "status",
    "traceLoad", "tracePrevious", "traceOver", "traceInto", "traceOut", "traceReset", "traceStatus",
    "traceToolbar", "traceButtons", "traceOverflow", "traceMenu"]) elements.set(id, new TestElement(id, document));
  const get = (id: string) => elements.get(id)!;
  get("traceToolbar").append(get("traceButtons"), get("traceOverflow"), get("traceMenu"));
  get("traceMenu").hidden = true;
  get("traceOverflow").width = 32;
  const context = { document, acquireVsCodeApi: () => ({ postMessage: (value: Record<string, unknown>) => messages.push(value) }),
    window: { addEventListener() {} }, ResizeObserver: class { observe() {} }, Option: TestElement };
  const source = readFileSync(resolve(__dirname, "../../media/callView.js"), "utf8");
  const api = runInNewContext(source + "\n({ traceLayout, layoutTraceToolbar, updateTrace, render });", context) as {
    traceLayout<T extends { width: number }>(buttons: T[], width: number, overflowWidth: number): { visible: T[]; overflow: T[] };
    layoutTraceToolbar(): void; updateTrace(state: unknown): void; render(state: unknown): void;
  };
  return { get, document, messages, ...api };
}
