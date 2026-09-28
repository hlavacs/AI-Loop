import * as assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { CoverageResponse, EvidenceKind, IssuesResponse, coverageNodes, issueNodes,
  parseEvidenceSelection, registerEvidenceCommands } from "../evidenceData";
import { EvidenceModel } from "../evidenceModel";
import { ProjectSession } from "../projectSession";
import { SessionContext } from "../protocol";

const context = { sessionId: "session", modelRevision: 1, targetId: null };
const base = { ...context, sourceRootId: "session:workspace", stale: false, staleReason: "" };
const location = { file: "main.py", line: 12, sourceRootId: base.sourceRootId };
const issues: IssuesResponse = { ...base, emptyReason: null, message: "", findings: [
  { ...location, id: "issue:1", ruleId: "missing-doxygen", severity: "warning", message: "Needs purpose", usr: "main" },
  { ...location, id: "issue:2", ruleId: "function-lines", severity: "error", message: "Too long", usr: "main" },
] };
const coverage: CoverageResponse = { ...base,
  requirementTraceability: { label: "Requirement Traceability", emptyReason: null, message: "", entries: [
    { id: "R-1", kind: "requirement", title: "Run", uncovered: false,
      entities: [{ ...location, usr: "main", qualifiedName: "main" }] },
    { id: "R-2", kind: "requirement", title: "Later", uncovered: true, entities: [] },
  ] },
  structuralTestReachability: { label: "Structural Test Reachability", emptyReason: null, message: "", uncovered: [],
    entries: [{ ...location, usr: "main", qualifiedName: "main", signature: "main()", covered: true, tests: ["test_main"],
      evidence: [{ step: 2, title: "Run test", time: "2026-09-28", tests: ["test_main"] }] }] },
};

function setup(kind: EvidenceKind, reply: (identity?: SessionContext) => unknown = () => kind === "issues" ? issues : coverage) {
  const logs: string[] = [];
  const session = new ProjectSession(text => logs.push(text), () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  const client = { request: async <T>(_method: string, _params = {}, identity?: SessionContext): Promise<T> =>
    await reply(identity) as T };
  return { session, logs, model: new EvidenceModel(kind, session, client, text => logs.push(text), () => {}) };
}

test("Issues groups core findings and preserves the offending call-site source", () => {
  const nodes = issueNodes(issues);
  assert.deepEqual(nodes.map(node => node.label), ["Warnings", "Errors"]);
  assert.equal(nodes[0]!.children![0]!.label, "Needs purpose");
  assert.equal(nodes[1]!.children![0]!.icon, "error");
  assert.equal(nodes[0]!.children![0]!.description, "missing-doxygen");
  assert.deepEqual(nodes[0]!.children![0]!.source, location);
  assert.equal(issueNodes({ ...issues, findings: [{ ...issues.findings[0]!, file: null }] })[0]!.children![0]!.source, undefined);
  assert.match(nodes[0]!.children![0]!.tooltip!, /main.py:12/);
});

test("Coverage maps two distinct sections with requirements, tests and step evidence", () => {
  const [requirements, structural] = coverageNodes(coverage);
  assert.ok(requirements && structural);
  assert.deepEqual([requirements.label, structural.label], ["Requirement Traceability", "Structural Test Reachability"]);
  assert.equal(requirements.children![0]!.description, "Linked");
  assert.equal(requirements.children![1]!.description, "Uncovered");
  assert.equal(requirements.children![1]!.source, undefined);
  assert.deepEqual(requirements.children![0]!.children![0]!.source, location);
  assert.equal(structural.children![0]!.description, "Reached");
  assert.match(structural.children![0]!.tooltip!, /test_main.*\n#2 Run test/);
  assert.deepEqual(structural.children![0]!.children![0]!.source, location);
  assert.doesNotMatch(JSON.stringify([requirements, structural]), /runtime code coverage/i);
});

test("all evidence empty states explain the missing input without hiding unreached callables", () => {
  for (const emptyReason of ["no_model", "no_findings"]) {
    const nodes = issueNodes({ ...issues, findings: [], emptyReason, message: `Explain ${emptyReason}` });
    assert.deepEqual(nodes, [{ id: emptyReason, label: `Explain ${emptyReason}`, tooltip: `Explain ${emptyReason}` }]);
  }
  for (const emptyReason of ["no_model", "no_specification", "no_requirements", "no_callables", "no_recorded_tests"]) {
    const result = { ...coverage, requirementTraceability: { ...coverage.requirementTraceability,
      entries: [], emptyReason, message: `Explain ${emptyReason}` },
    structuralTestReachability: { ...coverage.structuralTestReachability, emptyReason, message: `Explain ${emptyReason}` } };
    const nodes = coverageNodes(result);
    assert.equal(nodes[0]!.children![0]!.label, `Explain ${emptyReason}`);
    assert.equal(nodes[1]!.children![0]!.label, `Explain ${emptyReason}`);
    assert.equal(nodes[1]!.children![1]!.label, "main");
  }
});

test("tree selection commands reject malformed arguments and caller-supplied source paths", () => {
  const valid = { view: "issues", id: "issue:1", version: 1 };
  assert.deepEqual(parseEvidenceSelection(valid), valid);
  for (const value of [null, [], {}, { ...valid, file: "../secret" }, { ...valid, id: "" },
    { ...valid, view: "other" }, { ...valid, version: 1.5 }, { ...valid, version: -1 },
    { ...valid, id: "\0" }, { ...valid, id: "\ud800" }, { ...valid, id: "a".repeat(16385) }]) {
    assert.equal(parseEvidenceSelection(value), undefined);
  }
});

test("both native views and refresh commands are registered and wired into lifecycle", async () => {
  const calls: unknown[] = [], commands = new Map<string, (value?: unknown) => unknown>();
  registerEvidenceCommands((name, action) => commands.set(name, action), kind => calls.push(kind), item => calls.push(item));
  commands.get("icoda.refreshIssues")!(); commands.get("icoda.refreshCoverage")!();
  commands.get("icoda.revealEvidence")!({ file: "bad" });
  const selected = { view: "coverage", id: "callable:main", version: 2 };
  commands.get("icoda.revealEvidence")!(selected);
  assert.deepEqual(calls, ["issues", "coverage", selected]);
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  for (const name of ["Issues", "Coverage"]) {
    const id = `icoda.${name.toLowerCase()}`, command = `icoda.refresh${name}`;
    assert.ok(manifest.contributes.views.icoda.some((view: { id: string; name: string }) => view.id === id && view.name === `ICODA ${name}`));
    assert.ok(manifest.activationEvents.includes(`onView:${id}`));
    assert.ok(manifest.activationEvents.includes(`onCommand:${command}`));
    assert.ok(manifest.contributes.commands.some((item: { command: string; title: string; enablement: string }) =>
      item.command === command && item.title === `Refresh ${name}` && item.enablement === "icoda.projectOpen && isWorkspaceTrusted"));
    assert.ok(manifest.contributes.menus["view/title"].some((item: { command: string }) => item.command === command));
  }
  await checkAdapterWiring();
});

async function checkAdapterWiring(): Promise<void> {
  const root = resolve(__dirname, "../../src");
  const [extension, adapter] = await Promise.all([readFile(resolve(root, "extension.ts"), "utf8"),
    readFile(resolve(root, "evidenceTrees.ts"), "utf8")]);
  assert.match(extension, /new EvidenceTrees\(/);
  assert.match(extension, /this.evidence.sync\(\)/);
  assert.match(extension, /this.evidence.dispose\(\)/);
  assert.match(adapter, /registerEvidenceCommands\(/);
  assert.match(adapter, /revealSource\(/);
  assert.match(adapter, /vscode.workspace.isTrusted/);
  assert.match(adapter, /item.id = node.id/);
  assert.match(adapter, /new vscode.ThemeIcon\(node.icon\)/);
}

test("models only navigate current rendered source nodes and refresh without recomputing core results", async () => {
  for (const kind of ["issues", "coverage"] as const) {
    const { model, session } = setup(kind);
    await model.sync();
    const selection = { view: kind, id: kind === "issues" ? "issue:1" : "requirement:R-1:main", version: model.version };
    assert.deepEqual(model.select(selection), location);
    assert.equal(model.select({ ...selection, id: "absent" }), undefined);
    await model.sync(true);
    assert.equal(model.select(selection), undefined);
    assert.deepEqual(model.select({ ...selection, version: model.version }), location);
    session.reset(); await model.sync();
    assert.match(model.items()[0]!.label, /Open an ICODA project/);
    assert.equal(model.select(selection), undefined);
    model.dispose();
    await model.sync(true);
    assert.deepEqual(model.items(), []);
  }
});

test("session, revision and target changes drop late evidence results and refresh their identity", async () => {
  for (const change of ["revision", "target", "session"] as const) {
    let complete!: (value: IssuesResponse) => void;
    const pending = new Promise<IssuesResponse>(resolve => { complete = resolve; });
    let first = true;
    const { model, session } = setup("issues", identity => {
      if (first) { first = false; return pending; }
      return { ...issues, ...identity };
    });
    const loading = model.sync();
    if (change === "session") { session.reset(); session.identity.accept(session.identity.capture(), { ...context, sessionId: "new" }, "open"); }
    else session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2, targetId: change === "target" ? "new" : null },
      change === "target" ? { targetId: "new" } : "analyse");
    await model.sync();
    complete({ ...issues, findings: [] }); await loading;
    assert.equal(model.items()[0]!.children![0]!.id, "issue:1");
    assert.deepEqual(model.select({ view: "issues", id: "issue:1", version: model.version }), location);
  }
});

test("mismatched identities, overlapping refresh and disposal cannot publish obsolete evidence", async () => {
  for (const mismatch of [{ sessionId: "other" }, { modelRevision: 10 }, { targetId: "other" }]) {
    const { model, logs } = setup("issues", () => ({ ...issues, ...mismatch }));
    await model.sync();
    assert.equal(model.select({ view: "issues", id: "issue:1", version: model.version }), undefined);
    assert.ok(logs.some(text => text.startsWith("Dropped stale response")));
  }
  let complete!: (value: IssuesResponse) => void, first = true;
  const pending = new Promise<IssuesResponse>(resolve => { complete = resolve; });
  const { model } = setup("issues", () => { if (first) { first = false; return pending; } return issues; });
  const loading = model.sync();
  await model.sync(true); complete({ ...issues, findings: [] }); await loading;
  assert.equal(model.items()[0]!.children![0]!.id, "issue:1");
  const disposed = setup("issues", () => pending);
  const last = disposed.model.sync(); disposed.model.dispose(); await last;
  assert.deepEqual(disposed.model.items(), []);
});

test("evidence errors allow retry and stale analysis remains visible", async () => {
  let failed = true;
  const { model, logs } = setup("coverage", () => {
    if (failed) throw new Error("Unavailable");
    return { ...coverage, stale: true, staleReason: "Source changed" };
  });
  await model.sync();
  assert.match(model.items()[0]!.label, /Unable to load coverage.*Refresh/);
  assert.equal(logs.length, 1);
  failed = false; await model.sync(true);
  assert.match(model.items()[0]!.label, /Stale model: Source changed/);
  assert.equal(model.items()[1]!.label, "Requirement Traceability");
});
