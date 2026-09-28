import * as assert from "node:assert/strict";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { tmpdir } from "node:os";
import { analysedFile, AutomaticAnalysis, SourceChanges, watchSourcePaths } from "../sourceChanges";
import { ProjectSession } from "../projectSession";

const root = resolve("chosen project");

test("P05 debounced saves survive analysis publication but never cross project or target selections", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  for (const change of ["none", "analysis", "target", "project"]) {
    const session = new ProjectSession(() => {}, () => {});
    const context = { sessionId: "project", modelRevision: 1, targetId: null };
    session.identity.accept(session.identity.capture(), context, "open");
    session.data = { root, modelState: "fresh", staleReason: "", targets: [], entityCount: 1, edgeCount: 0 };
    let saved!: (document: { uri: { scheme: string; fsPath: string } }) => void;
    let mark!: (file: string) => void, requests = 0;
    const disposable = { dispose() {} };
    const file = resolve(__dirname, "../sourceEditor.js"), requireFromEditor = createRequire(file);
    const exports = {} as { watchSourceSaves: typeof import("../sourceEditor").watchSourceSaves };
    runInNewContext(await readFile(file, "utf8"), { exports, require: (id: string) => id === "vscode" ? {
      Uri: { file: (path: string) => path }, RelativePattern: class {},
      Disposable: { from: (...items: { dispose(): void }[]) => ({ dispose: () => items.forEach(item => item.dispose()) }) },
      workspace: { getConfiguration: () => ({ get: () => true }),
        onDidSaveTextDocument: (callback: typeof saved) => { saved = callback; return disposable; },
        createFileSystemWatcher: () => ({ ...disposable, onDidCreate: () => disposable,
          onDidChange: () => disposable, onDidDelete: () => disposable }) },
    } : id === "./sourceChanges" ? { ...requireFromEditor(id),
      watchSourcePaths: (_root: string, callback: typeof mark) => { mark = callback; return { ...disposable, saved() {} }; },
    } : requireFromEditor(id) });
    const listener = exports.watchSourceSaves(session, assert.fail, async () => { requests++; return true; });
    saved({ uri: { scheme: "file", fsPath: join(root, "main.py") } });
    if (change === "analysis") session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
    if (change === "target") session.identity.invalidate();
    if (change === "project") session.reset();
    mark("main.py");
    t.mock.timers.tick(300); await Promise.resolve(); await Promise.resolve();
    assert.equal(requests, change === "none" || change === "analysis" ? 1 : 0, change);
    if (requests) assert.equal(session.data?.modelState, "stale");
    listener.dispose();
  }
});

test("P05 automatic refresh retries busy or dirty guards and drops edits after selection or disposal", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const session = new ProjectSession(() => {}, () => {});
  session.identity.accept(session.identity.capture(), { sessionId: "project", modelRevision: 1, targetId: null }, "open");
  let allowed = false, requests = 0;
  const refresh = new AutomaticAnalysis(session, async () => { requests++; return allowed; }, assert.fail);
  const tick = async () => { t.mock.timers.tick(300); await Promise.resolve(); await Promise.resolve(); };
  refresh.changed(); refresh.changed();
  await tick(); assert.equal(requests, 1);
  allowed = true;
  await tick(); assert.equal(requests, 2);
  await tick(); assert.equal(requests, 2);
  refresh.changed(); session.identity.invalidate();
  await tick(); assert.equal(requests, 2);
  refresh.changed(); refresh.dispose();
  await tick(); assert.equal(requests, 2);
});

test("P05 edits during analysis refresh its new revision once without duplicating concurrent work", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const session = new ProjectSession(() => {}, () => {});
  const context = { sessionId: "project", modelRevision: 1, targetId: null };
  session.identity.accept(session.identity.capture(), context, "open");
  let finish!: () => void, requests = 0;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const refresh = new AutomaticAnalysis(session, async () => {
    requests++;
    if (requests === 1) {
      await gate;
      session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
    }
    return true;
  }, assert.fail);
  refresh.changed(); t.mock.timers.tick(300);
  refresh.changed(); t.mock.timers.tick(300);
  assert.equal(requests, 1);
  finish(); await gate; await Promise.resolve(); await Promise.resolve();
  t.mock.timers.tick(300); await Promise.resolve();
  assert.equal(requests, 2);
  refresh.dispose();
});

test("P05 external deletions resolve surviving parents and ignore deleted symlink escapes", async t => {
  const directory = await mkdtemp(join(tmpdir(), "icoda-delete-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const project = join(directory, "project"), outside = join(directory, "outside");
  await mkdir(project); await mkdir(outside);
  await symlink(outside, join(project, "escape"), "dir");
  const marks: string[] = [];
  const changes = watchSourcePaths(project, file => marks.push(file), assert.fail);
  t.after(() => changes.dispose());
  t.mock.timers.enable({ apis: ["setTimeout"] });
  await changes.saved(join(project, "escape", "missing.py"), true);
  t.mock.timers.tick(1000); assert.deepEqual(marks, []);
  await changes.saved(join(project, "removed", "main.py"), true);
  t.mock.timers.tick(1000); assert.deepEqual(marks, ["removed/main.py"]);
});

test("save filter accepts Python and all analysed C/C++ sources, headers and modules", () => {
  for (const extension of ["py", "c", "cc", "cpp", "cxx", "c++", "h", "hh", "hpp", "hxx", "h++", "inl",
    "cppm", "ixx", "mpp", "cxxm", "c++m", "ccm", "CPP"]) {
    assert.equal(analysedFile(root, join(root, "src", `main.${extension}`)), `src/main.${extension}`);
  }
});

test("save filter excludes siblings, traversal, metadata and unrelated extensions", () => {
  for (const path of [join(root + "-other", "main.py"), join(root, "..", "main.cpp"),
    join(root, ".git", "hook.py"), join(root, ".icoda", "worktree", "main.py"),
    join(root, "README.md"), join(root, "main.py.txt"), join(root, "script.js")]) {
    assert.equal(analysedFile(root, path), undefined);
  }
});

test("an in-root analysed save marks stale only after debounce", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const marks: string[] = [];
  const changes = new SourceChanges(root, file => marks.push(file));
  t.after(() => changes.dispose());
  changes.saved(join(root, "src", "main.py"));
  t.mock.timers.tick(999);
  assert.deepEqual(marks, []);
  t.mock.timers.tick(1);
  assert.deepEqual(marks, ["src/main.py"]);
});

test("ignored saves never schedule a stale mark or postpone a valid pending mark", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const marks: string[] = [];
  const changes = new SourceChanges(root, file => marks.push(file));
  t.after(() => changes.dispose());
  changes.saved(join(root + "-other", "main.py"));
  changes.saved(join(root, "README.md"));
  t.mock.timers.tick(1000);
  assert.deepEqual(marks, []);
  changes.saved(join(root, "main.py"));
  t.mock.timers.tick(500);
  changes.saved(join(root, "README.md"));
  t.mock.timers.tick(500);
  assert.deepEqual(marks, ["main.py"]);
});

test("rapid saves collapse to one mark naming the latest saved file", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const marks: string[] = [];
  const changes = new SourceChanges(root, file => marks.push(file));
  t.after(() => changes.dispose());
  changes.saved(join(root, "main.py"));
  t.mock.timers.tick(700);
  changes.saved(join(root, "library.py"));
  t.mock.timers.tick(999);
  assert.deepEqual(marks, []);
  t.mock.timers.tick(1);
  assert.deepEqual(marks, ["library.py"]);
});

test("dispose cancels pending marks and refuses later saves from a replaced listener", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const marks: string[] = [];
  const changes = new SourceChanges(root, file => marks.push(file));
  changes.saved(join(root, "main.py"));
  changes.dispose();
  changes.dispose();
  changes.saved(join(root, "library.py"));
  t.mock.timers.tick(2000);
  assert.deepEqual(marks, []);
});

test("a save through a symlinked parent marks the project stale and excludes escapes",
  { skip: process.platform === "win32" }, async t => {
    const directory = await mkdtemp(join(tmpdir(), "icoda-save-"));
    t.after(() => rm(directory, { recursive: true, force: true }));
    await mkdir(join(directory, "real", "project"), { recursive: true });
    await symlink(join(directory, "real"), join(directory, "alias"), "dir");
    const root = join(directory, "alias", "project");
    await writeFile(join(root, "main.py"), "def main(): pass\n");
    await writeFile(join(directory, "outside.py"), "pass\n");
    await symlink(join(directory, "outside.py"), join(root, "escape.py"));
    const session = new ProjectSession(() => {}, () => {});
    session.data = { root, modelState: "fresh", staleReason: "", entityCount: 1, edgeCount: 0, targets: [] };
    const changes = watchSourcePaths(root, file => session.markSaved(file), assert.fail);
    t.after(() => changes.dispose());
    t.mock.timers.enable({ apis: ["setTimeout"] });
    await changes.saved(join(root, "escape.py"));
    t.mock.timers.tick(1000);
    assert.equal(session.data.modelState, "fresh");
    await changes.saved(join(root, "main.py"));
    t.mock.timers.tick(1000);
    assert.equal(session.data.modelState, "stale");
    assert.match(session.data.staleReason, /Saved main.py/);
    session.data.modelState = "fresh";
    await changes.saved(join(directory, "real", "project", "main.py"));
    changes.dispose();
    await Promise.resolve();
    t.mock.timers.tick(1000);
    assert.equal(session.data.modelState, "fresh");
  });
