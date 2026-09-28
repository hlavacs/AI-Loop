import * as assert from "node:assert/strict";
import { test } from "node:test";
import { SessionContext } from "../protocol";
import { SessionState } from "../sessionState";

const initial: SessionContext = { sessionId: "project-a", modelRevision: 1, targetId: null };

function opened() {
  const logs: string[] = [];
  const state = new SessionState(message => logs.push(message));
  assert.equal(state.accept(state.capture(), initial, "open"), true);
  return { state, logs };
}

test("rejects responses with outdated session, revision or target without changing state", () => {
  const { state, logs } = opened();
  const ticket = state.capture();
  for (const response of [
    { ...initial, sessionId: "old-project" },
    { ...initial, modelRevision: 0 },
    { ...initial, targetId: "old-target" },
    { ...initial, modelRevision: 2 },
  ]) assert.equal(state.accept(ticket, response, "read"), false);
  assert.deepEqual(state.context, initial);
  assert.equal(logs.length, 4);
  assert.ok(logs.every(log => log.includes("Dropped stale response")));
});

test("accepts only v1 analysis and target revision transitions", () => {
  const { state } = opened();
  const analysed = { ...initial, modelRevision: 2, targetId: "executable" };
  assert.equal(state.accept(state.capture(), initial, "analyse"), false);
  assert.equal(state.accept(state.capture(), analysed, "analyse"), true);
  assert.equal(state.accept(state.capture(), analysed, { targetId: "executable" }), true);
  assert.equal(state.accept(state.capture(), { ...analysed, targetId: null }, { targetId: null }), false);
  const selected = { ...analysed, modelRevision: 3, targetId: null };
  assert.equal(state.accept(state.capture(), selected, { targetId: null }), true);
  assert.deepEqual(state.context, selected);
});

test("rejects late analysis after revision advance, project switch or backend restart", () => {
  const { state } = opened();
  const old = state.capture();
  const result = { ...initial, modelRevision: 2 };
  assert.equal(state.accept(old, { ...result, targetId: "target" }, { targetId: "target" }), true);
  assert.equal(state.accept(old, result, "analyse"), false);
  state.reset();
  assert.equal(state.accept(old, result, "analyse"), false);
  assert.equal(state.accept(state.capture(), { ...initial, sessionId: "project-b" }, "open"), true);
  assert.equal(state.accept(old, result, "analyse"), false);
  assert.equal(state.context?.sessionId, "project-b");
});

test("reset invalidates pending opens even when both contexts are empty", () => {
  const state = new SessionState(() => {});
  const old = state.capture();
  state.reset();
  assert.equal(state.accept(old, initial, "open"), false);
  assert.equal(state.capture().context, undefined);
  assert.equal(state.accept(state.capture(), initial, "open"), true);
  const context = state.context!;
  context.modelRevision = 99;
  assert.equal(state.context?.modelRevision, 1);
});
