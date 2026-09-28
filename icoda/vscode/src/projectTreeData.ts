import { ProjectData } from "./projectSession";
import { SessionContext, Target } from "./protocol";

export interface TargetSelection {
  context: SessionContext;
  targetId: string | null;
}

export interface ProjectTreeNode {
  id: string;
  label: string;
  description?: string;
  tooltip?: string;
  icon?: string;
  selection?: TargetSelection;
  children?: ProjectTreeNode[];
}

export interface ProjectTreeState {
  hasFolder: boolean;
  trusted: boolean;
  backendStarted: boolean;
  project?: ProjectData;
  context?: SessionContext;
}

/** Plain tree descriptions keep rendering decisions testable without the VS Code host. */
export function projectTreeData(state: ProjectTreeState): { message?: string; items: ProjectTreeNode[] } {
  const message = emptyMessage(state);
  if (message || !state.project || !state.context) return { message, items: [] };
  const project = state.project;
  return { items: [{
    id: "project", label: project.root, tooltip: project.root, icon: "folder-opened",
    children: [
      { id: "model", label: `Model: ${project.modelState}`, tooltip: project.staleReason || undefined,
        icon: project.modelState === "stale" ? "warning" : "symbol-structure" },
      { id: "entities", label: `Entities: ${project.entityCount}`, description: "whole project" },
      { id: "edges", label: `Edges: ${project.edgeCount}`, description: "whole project" },
      { id: "targets", label: "Targets", children: project.targets.map(target => targetNode(target, state.context!)) },
    ],
  }] };
}

function emptyMessage(state: ProjectTreeState): string | undefined {
  if (!state.hasFolder) return "Open a workspace folder, then run ICODA: Open Project.";
  if (!state.trusted) return "Trust the workspace before starting the ICODA Python backend.";
  if (!state.backendStarted) return "Backend not started. Run ICODA: Open Project to read project state and cache.";
  if (!state.project) return "Backend has no project open. Run ICODA: Open Project.";
  return undefined;
}

function targetNode(target: Target, context: SessionContext): ProjectTreeNode {
  const selected = target.id === context.targetId;
  return {
    id: `target:${target.id ?? "whole-project"}`, label: target.label,
    description: [selected ? "selected" : "", target.kind, target.configuration].filter(Boolean).join(" · "),
    tooltip: target.name,
    icon: selected ? "check" : target.kind === "library" ? "library" : "symbol-method",
    selection: { context: { ...context }, targetId: target.id },
  };
}
