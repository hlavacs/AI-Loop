import * as assert from "node:assert/strict";
import { test } from "node:test";
import { ProjectData } from "../projectSession";
import { projectTreeData, ProjectTreeState } from "../projectTreeData";
import { SessionContext, Target } from "../protocol";

const context: SessionContext = { sessionId: "a", modelRevision: 2, targetId: "app" };
const targets: Target[] = [
  { id: null, kind: "whole-project", name: "Whole Project", label: "Whole Project", configuration: null, entryUsr: null },
  { id: "app", kind: "executable", name: "app", label: "app (Debug)", configuration: "Debug", entryUsr: "main" },
  { id: "lib", kind: "library", name: "lib", label: "lib", configuration: "Release", entryUsr: null },
];
const project: ProjectData = {
  root: "/chosen/project", modelState: "fresh", staleReason: "", entityCount: 6, edgeCount: 5, targets,
};
const state: ProjectTreeState = { hasFolder: true, trusted: true, backendStarted: true, project, context };

for (const [name, overrides, message] of [
  ["no folder", { hasFolder: false }, "Open a workspace folder, then run ICODA: Open Project."],
  ["untrusted", { trusted: false }, "Trust the workspace before starting the ICODA Python backend."],
  ["not started", { backendStarted: false }, "Backend not started. Run ICODA: Open Project to read project state and cache."],
  ["no project", { project: undefined }, "Backend has no project open. Run ICODA: Open Project."],
] as const) {
  test(`tree empty state: ${name}`, () => {
    assert.deepEqual(projectTreeData({ ...state, ...overrides }), { message, items: [] });
  });
}

for (const modelState of ["none", "fresh", "stale", "analysing"] as const) {
  test(`tree renders ${modelState} model, whole-project counts and selected targets`, () => {
    const staleReason = modelState === "stale" ? "Syntax error in main.py" : "";
    const result = projectTreeData({ ...state, project: { ...project, modelState, staleReason } });
    assert.equal(result.message, undefined);
    assert.equal(result.items[0]?.label, "/chosen/project");
    const children = result.items[0]!.children!;
    assert.equal(children[0]?.label, `Model: ${modelState}`);
    assert.equal(children[0]?.tooltip, staleReason || undefined);
    assert.equal(children[1]?.label, "Entities: 6");
    assert.equal(children[2]?.label, "Edges: 5");
    assert.equal(children[1]?.description, "whole project");
    assert.equal(children[3]?.label, "Targets");
    const items = children[3]!.children!;
    assert.deepEqual(items.map(item => item.label), ["Whole Project", "app (Debug)", "lib"]);
    assert.equal(items[1]?.description, "selected · executable · Debug");
    assert.equal(items[2]?.description, "library · Release");
    assert.deepEqual(items[0]?.selection, { context, targetId: null });
    assert.deepEqual(items[1]?.selection, { context, targetId: "app" });
  });
}

test("Whole Project can be marked selected without marking executable or library", () => {
  const result = projectTreeData({ ...state, context: { ...context, targetId: null } });
  const items = result.items[0]!.children![3]!.children!;
  assert.equal(items.filter(item => item.description?.includes("selected")).length, 1);
  assert.equal(items[0]?.icon, "check");
});
