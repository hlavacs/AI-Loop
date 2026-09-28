import { constants } from "node:fs";
import { access, stat } from "node:fs/promises";
import { delimiter, join, resolve } from "node:path";

/** Installed packages carry their backend; source checkouts retain the parent layout. */
export async function resolveBackend(extensionRoot: string): Promise<string> {
  for (const root of [join(extensionRoot, "backend"), resolve(extensionRoot, "..")]) {
    try {
      if ((await stat(join(root, "icoda_core", "service.py"))).isFile()) return root;
    } catch { /* Try the development layout when the bundled service is absent. */ }
  }
  throw new Error("ICODA backend sources are missing. Reinstall the VSIX or run npm run package in the development checkout.");
}

/** Resolve the backend runtime; build-tool discovery stays in Python's toolchain.inspect. */
export async function resolvePython(packageRoot: string, configured = ""): Promise<string> {
  if (configured.trim()) {
    const command = configured.trim();
    const selected = await executable(command) ? command : /[\\/]/.test(command) ? undefined : await onPath([command]);
    if (selected) return selected;
    throw new Error(`Python executable "${command}" was not found or is not executable. Set icoda.pythonPath.`);
  }
  const relative = process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"];
  const local = join(packageRoot, ".icoda-venv", ...relative);
  if (await executable(local)) return local;
  const selected = await onPath(["python3", "python"]);
  if (selected) return selected;
  throw new Error("Python was not found. Install ICODA's Python dependencies and set icoda.pythonPath.");
}

async function onPath(names: string[]): Promise<string | undefined> {
  for (const name of names) {
    for (const directory of (process.env.PATH ?? "").split(delimiter).filter(Boolean)) {
      const candidate = join(directory, process.platform === "win32" && !name.toLowerCase().endsWith(".exe") ? `${name}.exe` : name);
      if (await executable(candidate)) return candidate;
    }
  }
  return undefined;
}

async function executable(path: string): Promise<boolean> {
  try {
    await access(path, constants.X_OK);
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
}
