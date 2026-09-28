import { copyFile, mkdir, readdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, resolve } from "node:path";
import { execFileSync } from "node:child_process";

const root = fileURLToPath(new URL("../", import.meta.url));
const backend = join(root, "backend");

try {
  await rm(backend, { recursive: true, force: true });
  await mkdir(join(backend, "icoda_core"), { recursive: true });
  const core = resolve(root, "../icoda_core");
  for (const entry of await readdir(core, { withFileTypes: true })) {
    if (entry.isFile() && /\.(py|json)$/.test(entry.name)) {
      await copyFile(join(core, entry.name), join(backend, "icoda_core", entry.name));
    }
  }
  await copyFile(resolve(root, "../constraints.txt"), join(backend, "constraints.txt"));
  await copyFile(resolve(root, "../../LICENSE"), join(backend, "LICENSE.txt"));
  await mkdir(join(root, "dist"), { recursive: true });
  // vsce uses this standard build timestamp to sort entries and fix ZIP mtimes.
  process.env.SOURCE_DATE_EPOCH ??= "315532800";
  execFileSync(process.execPath, [join(root, "node_modules/@vscode/vsce/vsce"), "package",
    "--no-dependencies", "--allow-missing-repository", "--out", join(root, "dist")], { cwd: root, stdio: "inherit" });
} finally {
  // Development must keep resolving live sources, even when staging or vsce fails.
  await rm(backend, { recursive: true, force: true });
}
