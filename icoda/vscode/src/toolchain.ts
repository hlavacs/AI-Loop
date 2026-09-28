/** Discovery belongs to icoda_core; the frontend only maps settings and presents its report. */
export interface ToolchainInspection {
  runtime: { python: string };
  tools: { name: string; path: string | null; source: "override" | "discovered" | "path" | "missing"; version?: string }[];
  environment: Record<string, string>;
  diagnostics: string[];
  errors: { code: "missing_tool"; message: string; details: { tool: string; setting: string } }[];
}

export function toolchainParams(get: (key: string) => string): Record<string, string> {
  const params: Record<string, string> = {};
  for (const key of ["cmakePath", "ninjaPath", "clangPath", "llvmSymbolizerPath"]) {
    const value = get(`toolchain.${key}`).trim();
    if (value) params[key] = value;
  }
  return params;
}

export function formatToolchain(report: ToolchainInspection): string {
  const lines = [`Effective Python: ${report.runtime.python}`, "ICODA toolchain:"];
  for (const tool of report.tools) {
    lines.push(`${tool.name}: ${tool.path ?? "unavailable"} [${tool.source}]${tool.version ? ` (${tool.version})` : ""}`);
  }
  for (const error of report.errors) lines.push(`${error.code}: ${error.message}`);
  for (const diagnostic of report.diagnostics) lines.push(`Discovery: ${diagnostic}`);
  lines.push("Child process environment additions (global environment unchanged):");
  const additions = Object.entries(report.environment).sort(([a], [b]) => a.localeCompare(b));
  lines.push(...(additions.length ? additions.map(([key, value]) => `${key}=${value}`) : ["(none)"]));
  return lines.join("\n");
}
