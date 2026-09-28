import * as assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test, TestContext } from "node:test";
import { resolveBackend, resolvePython } from "../pythonRuntime";

async function layout(t: TestContext) {
  const temporary = await mkdtemp(join(tmpdir(), "icoda packaged Grüße "));
  t.after(() => rm(temporary, { recursive: true, force: true }));
  const root = join(temporary, "icoda");
  const extension = join(root, "vscode");
  await mkdir(extension, { recursive: true });
  return { root, extension, bundled: join(extension, "backend") };
}

async function service(root: string): Promise<void> {
  await mkdir(join(root, "icoda_core"), { recursive: true });
  await writeFile(join(root, "icoda_core", "service.py"), "# fixture\n");
}

test("bundled backend wins over a neighbouring checkout without selecting an interpreter", async t => {
  const { root, extension, bundled } = await layout(t);
  await service(root);
  await service(bundled);
  assert.equal(await resolveBackend(extension), bundled);
  assert.equal(await resolvePython(bundled, process.execPath), process.execPath);
});

test("development backend is used when no staged service exists", async t => {
  const { root, extension, bundled } = await layout(t);
  await service(root);
  await mkdir(bundled);
  assert.equal(await resolveBackend(extension), root);
});

test("installed backend works without a checkout beside it", async t => {
  const { extension, bundled } = await layout(t);
  await service(bundled);
  assert.equal(await resolveBackend(extension), bundled);
});

test("missing backend or a directory named service.py produces an installation error", async t => {
  const { extension, bundled } = await layout(t);
  await mkdir(join(bundled, "icoda_core", "service.py"), { recursive: true });
  await assert.rejects(resolveBackend(extension), /backend sources are missing.*Reinstall the VSIX/);
});

async function packageFixture(t: TestContext, exitCode: number) {
  const fixture = await layout(t);
  const { root, extension, bundled } = fixture;
  await service(root);
  await service(bundled);
  await writeFile(join(bundled, "icoda_core", "removed.py"), "# stale source\n");
  await writeFile(join(root, "icoda_core", "providers.json"), "{}");
  await writeFile(join(root, "constraints.txt"), "# constraints\n");
  await writeFile(resolve(root, "../LICENSE"), "fixture licence\n");
  await mkdir(join(extension, "scripts"));
  await copyFile(resolve(__dirname, "../../scripts/package.mjs"), join(extension, "scripts/package.mjs"));
  const vsce = join(extension, "node_modules/@vscode/vsce");
  await mkdir(vsce, { recursive: true });
  await writeFile(join(vsce, "vsce"), `
    const assert = require("node:assert/strict");
    const { existsSync, readFileSync } = require("node:fs");
    assert.equal(existsSync("backend/icoda_core/removed.py"), false);
    assert.equal(readFileSync("backend/icoda_core/service.py", "utf8"), "# fixture\\n");
    assert.equal(readFileSync("backend/icoda_core/providers.json", "utf8"), "{}");
    assert.ok(existsSync("backend/constraints.txt") && existsSync("backend/LICENSE.txt"));
    console.log("Fresh backend staged");
    process.exit(${exitCode});
  `);
  return fixture;
}

for (const exitCode of [0, 1]) {
  test(`packaging ${exitCode ? "failure" : "success"} leaves development backend unshadowed`, async t => {
    const { root, extension, bundled } = await packageFixture(t, exitCode);
    const result = spawnSync(process.execPath, [join(extension, "scripts/package.mjs")], {
      cwd: extension, encoding: "utf8",
    });
    assert.equal(result.status, exitCode, result.stderr);
    assert.match(result.stdout, /Fresh backend staged/);
    await assert.rejects(stat(bundled), { code: "ENOENT" });
    assert.equal(await resolveBackend(extension), root);
  });
}
