import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

// G14's file gate keeps the worker pending until the host proves responsiveness or changes selection.
export const slowAnalysis = `
import time
original = service.Service.analyse_project
def analyse(self, project, params):
    self.notify({"method": "operation.progress", "params": {**project.context(), "message": "Slow analysis started"}})
    time.sleep(0.75)
    deadline = time.monotonic() + 10
    while not (project.store.root / "release-analysis").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Node event loop did not release analysis")
        time.sleep(0.01)
    return original(self, project, params)
service.Service.analyse_project = analyse
`;

export async function writeServiceShim(packageRoot: string, core: string, bootstrap: string): Promise<void> {
  const shim = join(packageRoot, "icoda_core");
  await mkdir(shim, { recursive: true });
  await writeFile(join(shim, "__init__.py"), `__path__.append(${JSON.stringify(core)})\n` + await readFile(join(core, "__init__.py"), "utf8"));
  // All protocol, analysis, cancellation and publication logic still comes from the actual service.
  await writeFile(join(shim, "service.py"), `import importlib.util,sys\nspec=importlib.util.spec_from_file_location('controlled_service',${JSON.stringify(join(core, "service.py"))})\nservice=importlib.util.module_from_spec(spec)\nsys.modules[spec.name]=service\nspec.loader.exec_module(service)\n${bootstrap}\nservice.main()\n`);
}
