import { SessionContext, isObject } from "./protocol";
import { providerSelection, SpecificationNode } from "./specificationData";

export const workflowCommands = [
  { command: "icoda.proposeArchitecture", title: "Propose Architecture", kind: "architecture" },
  { command: "icoda.proposeImplementationApproach", title: "Propose Implementation Approach", kind: "implementation_approach" },
  { command: "icoda.runImplementationQueue", title: "Run Implementation Queue", kind: "implementation_queue" },
  { command: "icoda.cancelAIWorkflow", title: "Cancel AI Workflow", kind: "cancel" },
  { command: "icoda.proposePurposeComments", title: "Propose Purpose Comments", kind: "purpose" },
  { command: "icoda.applyPurposeComments", title: "Apply Purpose Comments", kind: "purpose.apply" },
  { command: "icoda.rejectPurposeComments", title: "Reject Purpose Comments", kind: "purpose.reject" },
  { command: "icoda.queueBatchSize", title: "Set Queue Batch Size", kind: "queue.batchSize" },
  { command: "icoda.queueScope", title: "Set Queue Scope", kind: "queue.scope" },
  { command: "icoda.queueGrouping", title: "Set Queue Grouping", kind: "queue.grouping" },
  { command: "icoda.queueAutoApprove", title: "Set Queue Automatic Approval", kind: "queue.autoApprove" },
  { command: "icoda.sendConversation", title: "Send Conversation", kind: "conversation.send" },
  { command: "icoda.showConversation", title: "Show Conversation History", kind: "conversation.history" },
  { command: "icoda.rephrase", title: "Rephrase Current Description", kind: "prompt.rephrase" },
  { command: "icoda.openCLI", title: "Open CLI", kind: "cli.command" },
] as const;
export type WorkflowKind = typeof workflowCommands[number]["kind"];
export interface WorkflowInput {
  unsavedDocuments: string[]; idle?: boolean; request?: string; focus?: string[];
  provider?: string; model?: string;
  message?: string; draft?: string;
}
export interface WorkflowResult {
  round: string; summary: string; candidateLocation: string | null; files: string[];
  build?: { ok: boolean | null }; tests?: { ok: boolean | null };
}
export interface WorkflowStatus extends SessionContext {
  workflow: { id: string; kind: string; state: string; message: string; result: WorkflowResult | null;
    error: { code: string; message: string; details: Record<string, unknown> } | null; sourceChanged?: boolean } | null;
  queueSettings?: QueueSettings;
  continuation?: { state: "running" | "stopped"; reason: string; ready: boolean };
}
export interface QueueSettings {
  batchSize: number; scope: string; grouping: string; autoApprove: boolean;
  scopes: { value: string; label: string }[]; groupings: { value: string; label: string }[];
}
export type QueueSetting = "batchSize" | "scope" | "grouping" | "autoApprove";
export type QueuePatch = Partial<Pick<QueueSettings, QueueSetting>>;
export function validQueuePatch(value: unknown, settings?: QueueSettings): value is QueuePatch {
  if (!isObject(value) || !Object.keys(value).length || Object.keys(value).some(key =>
    !["batchSize", "scope", "grouping", "autoApprove"].includes(key))) return false;
  return (!("batchSize" in value) || Number.isSafeInteger(value.batchSize) && Number(value.batchSize) >= 1)
    && (!("autoApprove" in value) || typeof value.autoApprove === "boolean")
    && (!("scope" in value) || Boolean(settings?.scopes.some(item => item.value === value.scope)))
    && (!("grouping" in value) || Boolean(settings?.groupings.some(item => item.value === value.grouping)));
}
export interface WorkflowNode extends SpecificationNode { command?: string }

export interface ConversationHistory extends SessionContext { messages: { role: string; text: string }[] }
export interface CLICommand extends SessionContext { argv: string[]; cwd: string; env: Record<string, string> }
export function terminalOptions(value: CLICommand): { name: string; shellPath: string; shellArgs: string[]; cwd: string; env: Record<string, string> } {
  const text = (item: unknown): item is string => typeof item === "string" && !item.includes("\0");
  if (!Array.isArray(value.argv) || !value.argv.length || !value.argv.every(text) || !value.argv[0]
    || !text(value.cwd) || !value.cwd || !isObject(value.env)
    || !Object.entries(value.env).every(([key, item]) => text(key) && !key.includes("=") && text(item))) {
    throw new Error("Invalid ICODA CLI command.");
  }
  return { name: "ICODA CLI", shellPath: value.argv[0]!, shellArgs: value.argv.slice(1), cwd: value.cwd, env: value.env };
}
export function conversationText(history: ConversationHistory): string {
  return history.messages.map(item => `${item.role}:\n${item.text}`).join("\n\n");
}

export function registerWorkflowCommands<T>(register: (name: string, action: (...args: unknown[]) => unknown) => T,
  execute: (kind: WorkflowKind, title: string) => unknown): T[] {
  return workflowCommands.map(item => register(item.command, (...args) =>
    args.length ? undefined : execute(item.kind, item.title)));
}

export function validWorkflowInput(value: unknown): value is WorkflowInput {
  if (!isObject(value) || Object.keys(value).some(key =>
    !["unsavedDocuments", "idle", "request", "focus", "provider", "model", "message", "draft"].includes(key))) return false;
  const text = (item: unknown) => typeof item === "string" && item.length > 0 && !item.includes("\0");
  const strings = (items: unknown) => Array.isArray(items) && items.length <= 1000 && items.every(text);
  if (!strings(value.unsavedDocuments) || (value.focus !== undefined && !strings(value.focus))) return false;
  if (value.idle !== undefined && typeof value.idle !== "boolean") return false;
  if (value.request !== undefined && !text(value.request)) return false;
  for (const key of ["message", "draft"]) if (value[key] !== undefined
    && (!text(value[key]) || !(value[key] as string).trim() || (value[key] as string).length > 20000)) return false;
  return value.provider === undefined && value.model === undefined || Boolean(providerSelection({ provider: value.provider, model: value.model }));
}

export function workflowNodes(status?: WorkflowStatus): WorkflowNode[] {
  const job = status?.workflow;
  const nodes: WorkflowNode[] = workflowCommands.filter(item =>
    ["conversation.send", "conversation.history", "prompt.rephrase", "cli.command"].includes(item.kind))
    .map(item => ({ id: item.kind, label: item.title, command: item.command }));
  const settings = status?.queueSettings;
  if (settings) {
    for (const [key, label, description] of [
      ["batchSize", "Batch size", String(settings.batchSize)],
      ["scope", "Queue scope", settings.scopes.find(item => item.value === settings.scope)?.label ?? settings.scope],
      ["grouping", "Queue grouping", settings.groupings.find(item => item.value === settings.grouping)?.label ?? settings.grouping],
      ["autoApprove", "Auto-approve while gates pass", settings.autoApprove ? "On" : "Off"],
    ]) nodes.push({ id: `queue.${key}`, label: label!, description: description!,
      command: workflowCommands.find(item => item.kind === `queue.${key}`)!.command });
  }
  if (status?.continuation) nodes.push({ id: "continuation", label: `Automatic continuation: ${status.continuation.state}`,
    description: status.continuation.reason || "Continuing while approval gates pass." });
  if (!job) return [...nodes, { id: "idle", label: "No AI workflow in this project revision." }];
  nodes.push({ id: "state", label: `${job.kind}: ${job.state}`, description: job.message });
  if (job.error) nodes.push({ id: "error", label: job.error.code, description: job.error.message });
  const proposal = job.result;
  if (proposal) {
    nodes.push({ id: "summary", label: ["conversation.send", "prompt.rephrase"].includes(proposal.round)
      ? "Latest reply" : "Latest proposal", description: proposal.summary });
    if (proposal.candidateLocation) nodes.push({ id: "candidate", label: "Candidate", description: proposal.candidateLocation });
    for (const file of proposal.files) nodes.push({ id: `file:${file}`, label: file, description: "Proposed file" });
    if (proposal.build) nodes.push({ id: "build", label: "Build", description: String(proposal.build.ok) });
    if (proposal.tests) nodes.push({ id: "tests", label: "Tests", description: String(proposal.tests.ok) });
    if (proposal.round === "purpose" && job.state === "completed") {
      for (const command of workflowCommands.filter(item => item.kind === "purpose.apply" || item.kind === "purpose.reject")) {
        nodes.push({ id: command.kind, label: command.title, command: command.command });
      }
    }
  }
  return nodes;
}
