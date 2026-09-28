import * as assert from "node:assert/strict";
import { test } from "node:test";
import { parseCallViewMessage } from "../callViewMessages";
import { callViewHtml } from "../callViewHtml";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const version = 4;

test("accepts ready, select, viewport, depth, callers, root, filter and fit messages", () => {
  for (const message of [
    { type: "ready" }, { type: "select", version, usr: "python:main:B" },
    { type: "viewport", version, viewport: { x: -35, y: 10, scale: 1.2 } },
    { type: "depth", version, depth: 0 }, { type: "depth", version, depth: 12 },
    { type: "callers", version, callers: true }, { type: "callers", version, callers: false },
    { type: "root", version, usr: "main" }, { type: "root", version, usr: null },
    { type: "filter", version, text: "Grüße" }, { type: "filter", version, text: "" },
    { type: "fit", version, width: 800, height: 400 },
  ]) assert.deepEqual(parseCallViewMessage(message), message);
});

test("rejects unknown messages, stale identity shapes, extra fields and wrong field types", () => {
  for (const message of [null, [], "select", {}, { type: "eval", code: "alert(1)", version },
    { type: "ready", extra: 1 }, { type: "select", usr: "main" },
    { type: "select", version: "4", usr: "main" }, { type: "select", version: -1, usr: "main" },
    { type: "select", version, usr: 3 }, { type: "select", version, usr: "" },
    { type: "select", version, usr: "main\0" }, { type: "select", version, usr: "main", path: "/elsewhere" },
    { type: "depth", version, depth: 13 }, { type: "depth", version, depth: 1.5 },
    { type: "depth", version, depth: "3" }, { type: "depth", version, depth: true },
    { type: "callers", version, callers: "true" }, { type: "root", version, usr: [] },
    { type: "filter", version, text: 9 }, { type: "filter", version, text: "\0" },
    { type: "fit", version, width: 0, height: 500 }, { type: "fit", version, width: 500, height: Infinity },
    { type: "viewport", version, viewport: { x: 0, y: 0, scale: 0 } },
    { type: "viewport", version, viewport: { x: NaN, y: 0, scale: 1 } },
    { type: "viewport", version, viewport: { x: 0, y: "0", scale: 1 } },
    { type: "viewport", version, viewport: { x: 0, y: 0, scale: 1, extra: true } },
  ]) assert.equal(parseCallViewMessage(message), undefined, JSON.stringify(message));
});

test("rejects oversized UTF-8 payloads, oversized fields and cyclic objects", () => {
  for (const message of [
    { type: "select", version, usr: "a".repeat(4097) },
    { type: "filter", version, text: "a".repeat(257) },
    { type: "select", version, usr: "😀".repeat(16 * 1024) },
    { type: "ready", payload: "a".repeat(20 * 1024) },
  ]) assert.equal(parseCallViewMessage(message), undefined);
  const cycle: Record<string, unknown> = { type: "ready" };
  cycle.self = cycle;
  assert.equal(parseCallViewMessage(cycle), undefined);
});

test("HTML permits only nonce scripts and local styles; graph data never enters HTML", () => {
  const html = callViewHtml("randomNonce", "vscode-resource:", "vscode-resource:/callView.js", "vscode-resource:/callView.css");
  assert.match(html, /default-src 'none'; base-uri 'none'; form-action 'none'/);
  assert.match(html, /script-src 'nonce-randomNonce'/);
  assert.match(html, /script type="module" nonce="randomNonce" src="vscode-resource:\/callView.js"/);
  assert.doesNotMatch(html, /unsafe-inline|unsafe-eval|https?:\/\/|onchange=|onclick=/);
  assert.doesNotMatch(html, /Next\s+Call/);
});

test("trace messages accept only the named actions, version and bounded USR", () => {
  const messages = [{ type: "traceLoad", version }, { type: "traceReset", version },
    { type: "traceSeek", version, usr: "python:main:B" },
    ...["previous", "over", "into", "out"].map(action => ({ type: "traceStep", version, action }))];
  for (const message of messages) {
    assert.deepEqual(parseCallViewMessage(message), message);
    assert.equal(parseCallViewMessage({ ...message, path: "/injected.tsv" }), undefined);
    assert.equal(parseCallViewMessage({ ...message, version: -1 }), undefined);
  }
  for (const message of [{ type: "traceStep", version, action: "next" },
    { type: "traceStep", version, action: "seek" }, { type: "traceStep", version, action: 2 },
    { type: "traceReset", version, traceId: "injected" }, { type: "traceStep", version },
    { type: "traceLoad" }, { type: "traceSeek", version, usr: "" },
    { type: "traceSeek", version, usr: "B\0" }, { type: "traceSeek", version, usr: "x".repeat(4097) },
  ]) assert.equal(parseCallViewMessage(message), undefined);
});

test("Call View keeps six playback controls in one row with overflow and no redundant command", async () => {
  const html = callViewHtml("nonce", "local:", "local:script", "local:style");
  const toolbar = html.match(/<div id="toolbar"[\s\S]*?<\/div>/)![0];
  const labels = [...toolbar.matchAll(/<button id="trace\w+"[^>]*>([^<]+)<\/button>/g)].map(match => match[1]);
  assert.deepEqual(labels, ["Load Trace", "Previous Call", "Step Over", "Step Into", "Step Out", "Reset"]);
  assert.match(toolbar, /Trace playback/);
  assert.equal((html.match(/role="toolbar"/g) ?? []).length, 1);
  const root = resolve(__dirname, "../..");
  const css = await readFile(resolve(root, "media/callView.css"), "utf8");
  const js = await readFile(resolve(root, "media/callView.js"), "utf8");
  const manifest = await readFile(resolve(root, "package.json"), "utf8");
  assert.match(css, /#traceButtons \{[^}]*flex-wrap: nowrap/);
  assert.match(html, /aria-haspopup="menu" aria-controls="traceMenu" aria-expanded="false" hidden/);
  assert.doesNotMatch(html + js + manifest, /Next\s+Call|nextCall/);
  assert.match(js, /button.disabled = !next.trace\?\.availability\[action\]/);
});
