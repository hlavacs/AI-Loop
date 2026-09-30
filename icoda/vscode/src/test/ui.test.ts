import * as assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { registerTraceCommands } from "../callViewMessages";
import { CallViewModel } from "../callViewModel";
import { FileViewModel } from "../fileViewModel";
import { ClassViewModel } from "../classViewModel";
import { MindMapModel } from "../mindMapModel";
import { ProjectSession } from "../projectSession";
import { BackendError } from "../protocol";
import { viewError } from "../viewErrors";
import { callWebview } from "./webviewHarness";

const root = resolve(__dirname, "../..");
const actions = ["Load", "Previous", "Over", "Into", "Out", "Reset"];
const availability = { previous: false, over: false, into: true, out: true, reset: true };

test("overflow partition", () => {
  const { traceLayout } = callWebview();
  const items = actions.map((id, index) => ({ id, width: 100, disabled: index % 2 === 0 }));
  for (const [width, count] of [[1000, 6], [620, 6], [619, 5], [344, 3], [343, 2], [32, 0], [0, 0]]) {
    const result = traceLayout(items, width!, 32);
    assert.equal(result.visible.length, count);
    assert.deepEqual([...result.visible, ...result.overflow], items);
    [...result.visible, ...result.overflow].forEach((item, index) => assert.equal(item, items[index]));
  }
  assert.deepEqual(items.map(item => item.disabled), [true, false, true, false, true, false]);
});

test("overflow DOM state", () => {
  const view = callWebview(), get = view.get;
  view.updateTrace({ graph: {}, loading: false, trace: { availability, status: "Call 3 of 6" } });
  get("traceToolbar").clientWidth = 245;
  get("traceInto").focus();
  view.layoutTraceToolbar();
  assert.deepEqual(get("traceButtons").children.map(item => item.id), ["traceLoad", "tracePrevious"]);
  assert.deepEqual(get("traceMenu").children.map(item => item.id), ["traceOver", "traceInto", "traceOut", "traceReset"]);
  assert.equal(view.document.activeElement, get("traceOverflow"));
  assert.equal(get("traceOver").disabled, true);
  assert.equal(get("traceInto").disabled, false);
  assert.equal(get("traceInto").getAttribute("role"), "menuitem");
  view.updateTrace({ graph: {}, trace: { availability: { ...availability, into: false }, status: "End of trace" } });
  assert.equal(get("traceInto").disabled, true);
  get("traceToolbar").clientWidth = 1000;
  view.layoutTraceToolbar();
  assert.deepEqual(get("traceButtons").children.map(item => item.id), actions.map(action => `trace${action}`));
  assert.equal(get("traceOverflow").hidden, true);
  assert.equal(get("traceMenu").hidden, true);
  assert.equal(get("traceInto").getAttribute("role"), undefined);
  assert.equal(get("traceInto").disabled, true);
});

test("overflow keyboard", () => {
  const view = callWebview(), get = view.get;
  view.render({ type: "render", version: 7, choices: [], graph: { nodes: [], edges: [] },
    viewport: { x: 0, y: 0, scale: 1 }, trace: { availability, status: "B selected" } });
  get("traceToolbar").clientWidth = 245; view.layoutTraceToolbar();
  get("traceOverflow").emit("click");
  assert.equal(get("traceOverflow").getAttribute("aria-expanded"), "true");
  assert.equal(view.document.activeElement, get("traceInto"));
  get("traceMenu").emit("keydown", { key: "ArrowDown" });
  assert.equal(view.document.activeElement, get("traceOut"));
  get("traceMenu").emit("keydown", { key: "Home" });
  assert.equal(view.document.activeElement, get("traceInto"));
  get("traceInto").emit("click");
  assert.deepEqual(JSON.parse(JSON.stringify(view.messages.at(-1))), { type: "traceStep", version: 7, action: "into" });
  get("traceMenu").emit("keydown", { key: "Escape" });
  assert.equal(get("traceMenu").hidden, true);
  assert.equal(view.document.activeElement, get("traceOverflow"));
  get("traceOverflow").emit("keydown", { key: "ArrowDown" });
  get("traceToolbar").emit("focusout", { relatedTarget: get("graphQuery") });
  assert.equal(get("traceMenu").hidden, true);
});

test("scoped trace bindings", async () => {
  const manifest = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
  const registrations = new Map<string, () => Promise<void>>(), received: string[] = [];
  registerTraceCommands((id, action) => registrations.set(id, action), async action => { received.push(action); });
  assert.equal(manifest.contributes.keybindings.length, 5);
  for (const binding of manifest.contributes.keybindings) {
    assert.match(binding.when, /(?:^| && )activeWebviewPanelId == icoda\.callView(?: && |$)/);
    assert.match(binding.when, /!editorTextFocus && !inputFocus/);
    assert.match(binding.when, /icoda.projectOpen && isWorkspaceTrusted/);
    for (const key of [binding.key, binding.mac, binding.win, binding.linux].filter(Boolean)) {
      assert.doesNotMatch(key, /f10|f11/i);
    }
    assert.ok(registrations.has(binding.command));
    await registrations.get(binding.command)!();
  }
  assert.deepEqual(received, ["previous", "over", "into", "out", "reset"]);
  for (const command of manifest.contributes.commands) {
    assert.equal(command.category, "ICODA");
    assert.match(command.title, /^[A-Z][A-Za-z /]+$/);
    if (command.command !== "icoda.showOutput") assert.ok(command.enablement, command.command);
  }
});

test("theme color guard", () => {
  // No semantic literal exceptions are currently needed. Any addition must document its purpose here.
  const semanticColorAllowlist = new Set<string>();
  const keywords = new Set(["none", "solid", "dashed", "transparent", "currentColor", "inherit"]);
  for (const name of readdirSync(resolve(root, "media")).filter(file => file.endsWith(".css"))) {
    const css = readFileSync(resolve(root, "media", name), "utf8");
    for (const match of css.matchAll(/(?:^|[;{])\s*([\w-]+)\s*:\s*([^;{}]+)/g)) {
      const value = match[2]!;
      for (const literal of value.match(/#[\da-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|oklch|lab|lch|color)\([^)]*\)/gi) ?? []) {
        assert.ok(semanticColorAllowlist.has(literal), `${name}: ${literal}`);
      }
      if (!/^(color|background|fill|stroke|border|outline|accent-color)(-|$)/.test(match[1]!)) continue;
      const plain = value.replace(/var\(--[\w-]+/g, "").replace(/url\([^)]*\)/g, "").replace(/[\d.]+(?:px|em|vh|vw|%)?/g, "");
      for (const word of plain.match(/[a-zA-Z]+/g) ?? []) assert.ok(keywords.has(word), `${name}: ${word}`);
    }
    assert.match(css, /var\(--vscode-/);
    assert.doesNotMatch(css, /outline:\s*none/);
  }
  const base = readFileSync(resolve(root, "media/callView.css"), "utf8");
  assert.match(base, /vscode-high-contrast-light/); assert.match(base, /vscode-high-contrast/);
  assert.match(base, /:focus-visible\s*\{[^}]*outline:/);
  for (const name of ["fileView", "classView", "mindMap"]) {
    assert.match(readFileSync(resolve(root, `media/${name}.css`), "utf8"), /@import url\('\.\/(callView|fileView)\.css'\)/);
  }
});

test("graph keyboard access", () => {
  for (const name of ["callView", "fileView", "classView", "mindMap"]) {
    const script = readFileSync(resolve(root, `media/${name}.js`), "utf8");
    assert.match(script, /tabindex: 0, role: "button"/);
    assert.match(script, /\["Enter", " "\]\.includes\(event.key\)/);
    assert.match(script, /event.preventDefault\(\)/);
    assert.match(script, /event.stopPropagation\(\)/);
  }
});

test("view empty/errors", async () => {
  for (const Model of [CallViewModel, FileViewModel, ClassViewModel, MindMapModel]) {
    const project = new ProjectSession(() => {}, () => {});
    let failure = new BackendError("model_unavailable", "No analysed model.");
    const view = new Model(project, { request: async () => { throw failure; } }, () => {}, () => {});
    assert.match(view.render().message, /ICODA: Open Project/);
    project.identity.accept(project.identity.capture(), { sessionId: "project", modelRevision: 1, targetId: null }, "open");
    await view.sync();
    assert.match(view.render().message, /ICODA: Analyse Project/);
    failure = new BackendError("backend_exited", "Connection closed.");
    project.identity.accept(project.identity.capture(), { sessionId: "project", modelRevision: 2, targetId: null }, "analyse");
    await view.sync();
    assert.match(view.render().message, /ICODA: Restart Backend/);
    assert.doesNotMatch(view.render().message, /backend_exited|BackendError/);
    view.dispose();
  }
  assert.match(viewError(new BackendError("invalid_trace", "Bad header.")), /valid recording.*Bad header/);
  assert.equal(viewError(new BackendError("new_code", "Useful explanation.")), "Useful explanation.");
});

test("trace empty states", () => {
  const view = callWebview();
  view.updateTrace({ graph: {}, trace: undefined });
  assert.match(view.get("traceStatus").textContent, /No trace loaded. Choose Load Trace/);
  for (const status of ["No function calls in trace", "No project functions resolved; check the selected executable."]) {
    view.updateTrace({ graph: {}, trace: { status, availability: {} } });
    assert.ok(view.get("traceStatus").textContent.endsWith(status));
    for (const action of actions.slice(1)) assert.equal(view.get(`trace${action}`).disabled, true);
  }
});
