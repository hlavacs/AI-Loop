import { isObject, SessionContext, SourceReference } from "./protocol";

export type EvidenceKind = "issues" | "coverage";
interface EmptyState { emptyReason: string | null; message: string }
interface EvidenceResponse extends SessionContext { sourceRootId: string; stale: boolean; staleReason: string }
interface Location { file: string | null; line: number; sourceRootId: string }
export interface Finding extends Location {
  id: string; ruleId: string; severity: string; message: string; usr: string | null;
}
export interface IssuesResponse extends EvidenceResponse, EmptyState { findings: Finding[] }
export interface RequirementEntry {
  id: string; kind: string; title: string; uncovered: boolean;
  entities: (Location & { usr: string; qualifiedName: string })[];
}
export interface ReachabilityEntry extends Location {
  usr: string; qualifiedName: string; signature: string; covered: boolean; tests: string[];
  evidence: { step: number; title: string; time: string; tests: string[] }[];
}
export interface CoverageResponse extends EvidenceResponse {
  requirementTraceability: EmptyState & { label: string; entries: RequirementEntry[] };
  structuralTestReachability: EmptyState & { label: string; entries: ReachabilityEntry[]; uncovered: string[] };
}
export interface EvidenceNode {
  id: string; label: string; description?: string; tooltip?: string; icon?: string;
  children?: EvidenceNode[]; expanded?: boolean; source?: SourceReference;
}
export interface EvidenceSelection { view: EvidenceKind; id: string; version: number }

export function messageNode(id: string, label: string): EvidenceNode { return { id, label, tooltip: label }; }

function source(location: Location): SourceReference | undefined {
  return location.file ? { sourceRootId: location.sourceRootId, file: location.file, line: location.line } : undefined;
}

/** Group the core findings without evaluating rules in the frontend. */
export function issueNodes(result: IssuesResponse): EvidenceNode[] {
  if (result.emptyReason) return [messageNode(result.emptyReason, result.message)];
  const groups = new Map<string, EvidenceNode>();
  for (const finding of result.findings) {
    if (!groups.has(finding.severity)) groups.set(finding.severity, {
      id: finding.severity, label: finding.severity === "error" ? "Errors" : "Warnings", children: [], expanded: true,
    });
    groups.get(finding.severity)!.children!.push({ id: finding.id, label: finding.message,
      description: finding.ruleId, tooltip: `${finding.ruleId}: ${finding.message}\n${finding.file ?? "No source"}:${finding.line}`,
      icon: finding.severity === "error" ? "error" : "warning", source: source(finding) });
  }
  return [...groups.values()];
}

export function coverageNodes(result: CoverageResponse): EvidenceNode[] {
  const requirements = result.requirementTraceability, structural = result.structuralTestReachability;
  return [section("requirements", requirements, requirements.entries.map(requirementNode)),
    section("structural", structural, structural.entries.map(reachabilityNode))];
}

function section(id: string, state: EmptyState & { label: string }, children: EvidenceNode[]): EvidenceNode {
  if (state.emptyReason) children.unshift(messageNode(`${id}:${state.emptyReason}`, state.message));
  return { id, label: state.label, children, expanded: true };
}

function requirementNode(entry: RequirementEntry): EvidenceNode {
  const id = `${entry.kind}:${entry.id}`, description = entry.uncovered ? "Uncovered" : "Linked";
  const children = entry.entities.map(entity => ({ id: `${id}:${entity.usr}`, label: entity.qualifiedName,
    description: `${entity.file ?? "No source"}:${entity.line}`, source: source(entity) }));
  if (!children.length) return { id, label: `${entry.id}: ${entry.title}`, description,
    tooltip: "No current entity has an exact matching @satisfies tag." };
  return { id, label: `${entry.id}: ${entry.title}`, description, children };
}

function reachabilityNode(entry: ReachabilityEntry): EvidenceNode {
  return { id: `callable:${entry.usr}`, label: entry.qualifiedName, description: entry.covered ? "Reached" : "Not reached",
    tooltip: [entry.signature, `${entry.file ?? "No source"}:${entry.line}`,
      entry.tests.length ? `Tests: ${entry.tests.join(", ")}` : "No reaching recorded test",
      ...entry.evidence.map(item => `#${item.step} ${item.title} (${item.time}): ${item.tests.join(", ")}`)].join("\n"),
    source: source(entry), children: entry.evidence.length ? entry.evidence.map((item, index) => ({
      id: `callable:${entry.usr}:evidence:${index}`, label: `#${item.step} ${item.title}`,
      description: item.tests.join(", "), tooltip: `${item.time}\n${item.tests.join("\n")}`, source: source(entry),
    })) : undefined };
}

/** Tree commands carry only a rendered node identity; never accept caller-supplied paths. */
export function parseEvidenceSelection(value: unknown): EvidenceSelection | undefined {
  if (!isObject(value) || Object.keys(value).sort().join(",") !== "id,version,view") return undefined;
  if (value.view !== "issues" && value.view !== "coverage") return undefined;
  if (typeof value.id !== "string" || !value.id || value.id.length > 16384 || value.id.includes("\0")
      || Buffer.from(value.id, "utf8").toString("utf8") !== value.id) return undefined;
  if (typeof value.version !== "number" || !Number.isSafeInteger(value.version) || value.version < 1) return undefined;
  return value as unknown as EvidenceSelection;
}

export function registerEvidenceCommands<T>(register: (name: string, action: (value?: unknown) => unknown) => T,
  refresh: (kind: EvidenceKind) => unknown, select: (selection: EvidenceSelection) => unknown): T[] {
  return [register("icoda.refreshIssues", () => refresh("issues")),
    register("icoda.refreshCoverage", () => refresh("coverage")),
    register("icoda.revealEvidence", value => {
      const selection = parseEvidenceSelection(value);
      return selection ? select(selection) : undefined;
    })];
}
