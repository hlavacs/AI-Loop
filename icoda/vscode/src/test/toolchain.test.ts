import * as assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { formatToolchain, toolchainParams, ToolchainInspection } from "../toolchain";
import { resolvePython } from "../pythonRuntime";

test("toolchain settings map to v1 params without Python or blank overrides", () => {
  const settings: Record<string, string> = {
    pythonPath: "/runtime/python", "toolchain.cmakePath": " /tools ü/cmake ",
    "toolchain.ninjaPath": "ninja", "toolchain.clangPath": "C:\\LLVM Tools\\clang++.exe",
    "toolchain.llvmSymbolizerPath": "/tools/llvm-symbolizer",
  };
  assert.deepEqual(toolchainParams(key => settings[key] ?? ""), {
    cmakePath: "/tools ü/cmake", ninjaPath: "ninja", clangPath: "C:\\LLVM Tools\\clang++.exe",
    llvmSymbolizerPath: "/tools/llvm-symbolizer",
  });
  assert.deepEqual(toolchainParams(() => "   "), {});
});

test("output includes effective Python, every path/source, errors and only returned environment additions", () => {
  const report: ToolchainInspection = {
    runtime: { python: "/runtime/python" }, tools: [
      { name: "cmake", path: "/tools/cmake", source: "override", version: "4.0" },
      { name: "ninja", path: "/vs/ninja", source: "discovered" },
      { name: "clang", path: "/bin/clang++", source: "path" },
      { name: "llvm-symbolizer", path: null, source: "missing" },
    ], environment: { PATH: "/tools:/vs:/bin", INCLUDE: "/sdk" }, diagnostics: ["SDK unavailable"],
    errors: [{ code: "missing_tool", message: "llvm-symbolizer is unavailable. Configure icoda.toolchain.llvmSymbolizerPath.",
      details: { tool: "llvm-symbolizer", setting: "icoda.toolchain.llvmSymbolizerPath" } }],
  };
  assert.equal(formatToolchain(report), [
    "Effective Python: /runtime/python", "ICODA toolchain:", "cmake: /tools/cmake [override] (4.0)",
    "ninja: /vs/ninja [discovered]", "clang: /bin/clang++ [path]", "llvm-symbolizer: unavailable [missing]",
    "missing_tool: llvm-symbolizer is unavailable. Configure icoda.toolchain.llvmSymbolizerPath.",
    "Discovery: SDK unavailable", "Child process environment additions (global environment unchanged):",
    "INCLUDE=/sdk", "PATH=/tools:/vs:/bin",
  ].join("\n"));
  assert.match(formatToolchain({ ...report, environment: {} }), /\n\(none\)$/);
});

test("manifest contributes trusted Show Toolchain and all five runtime/tool settings", async () => {
  const root = resolve(__dirname, "../..");
  const manifest = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  const command = manifest.contributes.commands.find((item: { command: string }) => item.command === "icoda.showToolchain");
  assert.deepEqual(command, { command: "icoda.showToolchain", title: "Show Toolchain", category: "ICODA", enablement: "isWorkspaceTrusted" });
  assert.ok(manifest.activationEvents.includes("onCommand:icoda.showToolchain"));
  for (const name of ["pythonPath", "toolchain.cmakePath", "toolchain.ninjaPath", "toolchain.clangPath", "toolchain.llvmSymbolizerPath"]) {
    const key = `icoda.${name}`;
    const setting = manifest.contributes.configuration.properties[key];
    assert.equal(setting.type, "string");
    assert.equal(setting.default, "");
    assert.equal(setting.scope, "machine-overridable");
    assert.ok(manifest.capabilities.untrustedWorkspaces.restrictedConfigurations.includes(key));
  }
});

test("Python runtime still honours the configured executable without toolchain discovery", async () => {
  assert.equal(await resolvePython("/unused", ` ${process.execPath} `), process.execPath);
  await assert.rejects(resolvePython("/unused", "/missing-icoda-runtime/python"), /Python executable.*icoda\.pythonPath/);
  await assert.rejects(resolvePython("/unused", __dirname), /not executable.*icoda\.pythonPath/);
});
