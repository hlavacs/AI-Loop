import * as assert from "node:assert/strict";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { BackendError, ProjectModel, ResolvedSource } from "../protocol";
import { entityChoices, resolveSource, sourceOutcome } from "../sourceNavigation";
import { ProjectSession } from "../projectSession";

const root = resolve("chosen project Grüße");
const resolved: ResolvedSource = {
  sessionId: "session", sourceRootId: "source", modelRevision: 2, targetId: null,
  file: "relocated/main.py", path: join(root, "relocated", "main.py"), line: 14,
};

test("P05 checked candidate source resolves against its own root and rejects foreign or expired roots", async () => {
  const session = new ProjectSession(() => {}, () => {});
  const context = { sessionId: "session", modelRevision: 1, targetId: null };
  session.identity.accept(session.identity.capture(), context, "open");
  session.sourceRootId = "workspace";
  session.data = { root, modelState: "fresh", staleReason: "", targets: [], entityCount: 1, edgeCount: 0 };
  const candidate = { ...context, root: join(root, ".icoda/worktree"), sourceRootId: "checked-candidate" };
  const ref = { sourceRootId: candidate.sourceRootId, usr: "new" };
  let requests = 0;
  const client = { request: async <T>(method: string, params: object = {}) => {
    requests++;
    assert.equal(method, "source.resolve"); assert.deepEqual(params, ref);
    return { ...context, sourceRootId: candidate.sourceRootId, file: "main.py", line: 2,
      path: join(candidate.root, "main.py") } as T;
  } };
  assert.deepEqual(await resolveSource(client, session, ref, candidate), {
    kind: "open", uri: pathToFileURL(join(candidate.root, "main.py")).href, line: 2, column: 1,
  });
  assert.equal((await resolveSource(client, session, ref))?.kind, "error");
  session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
  assert.equal((await resolveSource(client, session, ref, candidate))?.kind, "error");
  assert.equal(requests, 1);
});

test("single or relocated source maps to an escaped file URI and one-based coordinates", () => {
  for (const file of ["main.py", "relocated/main.py", "space # Grüße.py"]) {
    const response = { ...resolved, file, path: join(root, file) };
    assert.deepEqual(sourceOutcome(root, response), {
      kind: "open", uri: pathToFileURL(response.path).href, line: 14, column: 1,
    });
  }
});

test("equally ranked source candidates remain a choice with the original entity line", () => {
  const candidates = ["one/main.py", "two/main.py"];
  assert.deepEqual(sourceOutcome(root, new BackendError("source_ambiguous", "Choose source", {
    candidates, line: 14,
  })), { kind: "choose", candidates, line: 14 });
});

test("missing source stays local and other typed backend errors retain their codes", () => {
  assert.deepEqual(sourceOutcome(root, new BackendError("source_missing", "No source for this entity.")), {
    kind: "missing", message: "The source file could not be found in this project. No source for this entity.",
  });
  for (const code of ["invalid_params", "invalid_session", "stale_revision", "stale_target"]) {
    const outcome = sourceOutcome(root, new BackendError(code, "Cannot resolve source"));
    assert.equal(outcome.kind, "error");
    if (outcome.kind !== "error") assert.fail();
    assert.equal(outcome.code, code);
    assert.ok(outcome.message.endsWith("Cannot resolve source"));
    assert.ok(!outcome.message.includes(code));
  }
});

test("source outcomes refuse boundary escapes and unsafe ambiguity candidates", () => {
  for (const path of [join(root + "-other", "main.py"), join(root, "..", "main.py"), join(root, ".icoda", "main.py")]) {
    assert.equal(sourceOutcome(root, { ...resolved, path }).kind, "error");
  }
  assert.equal(sourceOutcome(root, new BackendError("source_ambiguous", "Choose source", {
    candidates: ["one/main.py", "../other/main.py"], line: 14,
  })).kind, "error");
});

test("entity picker contains files, classes and callables with stable source references", () => {
  const kinds = ["class", "struct", "function", "method", "constructor", "destructor", "field", "namespace"];
  const model: ProjectModel = { files: [{ path: "empty.py" }, { path: "../external.py" }],
    entities: kinds.map(kind => ({ usr: kind, kind, name: kind, file: "main.py", line: 3 })),
    edges: [], stale: false, stale_reason: "" };
  const choices = entityChoices(model, root, "source");
  assert.equal(choices.length, 7);
  assert.deepEqual(choices.find(item => item.description === "file")?.ref, { sourceRootId: "source", file: "empty.py" });
  assert.deepEqual(choices.find(item => item.description === "function")?.ref, { sourceRootId: "source", usr: "function" });
  assert.equal(choices.find(item => item.description === "class")?.detail, "main.py:3");
  assert.equal(entityChoices({ ...model, files: [], entities: [{ usr: "external", kind: "function", file: "../x.py" }] }, root, "source").length, 0);
});
