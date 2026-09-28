import { isAbsolute, join, win32 } from "node:path";
import { BackendError, isObject, ProjectSnapshot, SessionContext } from "./protocol";

export const proposalCommands = [
  { command: "icoda.reviewProposal", title: "Review Proposal", method: "proposal.get" },
  { command: "icoda.approveProposal", title: "Approve Proposal", method: "proposal.approve" },
  { command: "icoda.rejectProposal", title: "Reject Proposal", method: "proposal.reject" },
  { command: "icoda.adaptProposal", title: "Adapt Proposal", method: "proposal.adapt" },
  { command: "icoda.rebuildProposal", title: "Rebuild Proposal", method: "proposal.rebuild" },
  { command: "icoda.undoLastStep", title: "Undo Last Step", method: "step.undo" },
  { command: "icoda.commitManualEdits", title: "Commit Manual Edits", method: "step.commitManual" },
  { command: "icoda.showStepHistory", title: "Show Step History", method: "history.list" },
] as const;
export interface Gate { ok: boolean | null; output: string }
export interface CandidateFile { path: string; status: "A" | "M" | "D" }
export interface Proposal {
  round: "code" | "approach"; number: number; summary: string; worktreeRoot: string | null;
  files: CandidateFile[]; delta: string; error: string; entitySummary: string;
  signatureChanges: { usr: string; display_name: string; previous_signature: string; proposed_signature: string }[];
  build: Gate | null; tests: Gate | null; evidenceFresh: boolean; canApprove: boolean;
}
export interface StepRecord {
  number: number; round: string; decision: string; title: string; reason: string; rationale: string;
  commit: string; files: string[]; build_output: string; test_output: string;
}
export interface ProposalReview extends SessionContext {
  projectRoot: string; evidenceFingerprint: string; proposal: Proposal | null;
  candidateGraph?: { sourceRootId: string; root: string } | null;
  records: StepRecord[]; autoApprove: boolean; message: string;
}
export interface CandidateSource extends SessionContext { sourceRootId: string; root: string }
export interface DecisionResult extends ProjectSnapshot { record: StepRecord | null; records: StepRecord[] }
export interface ReviewInput { unsavedDocuments: string[]; confirmSignatures?: boolean; reason?: string; constraints?: string[]; entitySummary?: string }
export interface CandidateSelection extends SessionContext { path: string; evidenceFingerprint: string }
export type RecoveryChoice = "resume" | "keep" | "discard";
export interface RecoveryItem { id: string; label: string; worktreeRoot: string; choices: { value: RecoveryChoice; label: string }[] }
export interface RecoveryList extends SessionContext { items: RecoveryItem[] }
export interface RecoverySelection extends SessionContext { recoveryId: string }
export interface ProposalNode { id: string; label: string; description?: string; selection?: CandidateSelection; recovery?: RecoverySelection }

export function registerProposalCommands<T>(register: (name: string, action: (...args: unknown[]) => unknown) => T,
  execute: (method: string) => unknown, diff: (selection: CandidateSelection) => unknown,
  recover: (selection?: RecoverySelection) => unknown = () => {}): T[] {
  return [...proposalCommands.map(item => register(item.command, (...args) => args.length ? undefined : execute(item.method))),
    register("icoda.recoverProposal", (...args) => !args.length ? recover() : args.length === 1 && validRecoverySelection(args[0]) ? recover(args[0]) : undefined),
    register("icoda.openProposalDiff", (...args) => args.length === 1 && validCandidateSelection(args[0]) ? diff(args[0]) : undefined)];
}

export function validRecoverySelection(value: unknown): value is RecoverySelection {
  return isObject(value) && Object.keys(value).length === 4
    && Object.keys(value).every(key => ["sessionId", "modelRevision", "targetId", "recoveryId"].includes(key))
    && typeof value.sessionId === "string" && Boolean(value.sessionId) && !value.sessionId.includes("\0")
    && Number.isInteger(value.modelRevision) && Number(value.modelRevision) > 0
    && (value.targetId === null || typeof value.targetId === "string")
    && typeof value.recoveryId === "string" && /^[a-f0-9]{64}$/.test(value.recoveryId);
}

export function validReviewInput(method: string, value: unknown): value is ReviewInput {
  if (!isObject(value)) return false;
  const optional: Record<string, string[]> = { "proposal.approve": ["confirmSignatures"], "proposal.reject": ["reason"],
    "proposal.adapt": ["constraints", "entitySummary"], "proposal.rebuild": [], "step.undo": [], "step.commitManual": [] };
  const allowed = optional[method];
  const text = (item: unknown) => typeof item === "string" && Boolean(item.trim()) && !item.includes("\0");
  const strings = (items: unknown) => Array.isArray(items) && items.length <= 1000 && items.every(text);
  if (!allowed || Object.keys(value).some(key => !["unsavedDocuments", ...allowed].includes(key)) || !strings(value.unsavedDocuments)) return false;
  if (value.confirmSignatures !== undefined && typeof value.confirmSignatures !== "boolean") return false;
  if (method === "proposal.reject" && !text(value.reason)) return false;
  return (value.constraints === undefined || strings(value.constraints)) && (value.entitySummary === undefined || text(value.entitySummary));
}

export function validCandidateSelection(value: unknown): value is CandidateSelection {
  return isObject(value) && Object.keys(value).every(key => ["sessionId", "modelRevision", "targetId", "path", "evidenceFingerprint"].includes(key))
    && typeof value.sessionId === "string" && Boolean(value.sessionId) && Number.isInteger(value.modelRevision) && Number(value.modelRevision) > 0
    && (value.targetId === null || typeof value.targetId === "string") && typeof value.evidenceFingerprint === "string"
    && Boolean(value.evidenceFingerprint) && typeof value.path === "string" && relativeCandidatePath(value.path);
}

function relativeCandidatePath(path: string): boolean {
  return Boolean(path) && !path.includes("\0") && !path.includes("\\") && !path.includes(":")
    && !isAbsolute(path) && !path.split("/").some(part => !part || part === "." || part === "..");
}

/** Roots originate in the scoped backend review; command arguments may select only its listed relative paths. */
export function candidateDiff(review: ProposalReview, path: string): { original: string | null; candidate: string | null } {
  const proposal = review.proposal, file = proposal?.files.find(item => item.path === path);
  if (!file || !proposal?.worktreeRoot || !relativeCandidatePath(path)) throw new BackendError("invalid_params", "Choose a current candidate file.");
  const absolute = (root: string) => {
    if (!isAbsolute(root) && !win32.isAbsolute(root)) throw new BackendError("invalid_params", "Invalid review source root.");
    return win32.isAbsolute(root) && !isAbsolute(root) ? win32.join(root, ...path.split("/")) : join(root, path);
  };
  return { original: file.status === "A" ? null : absolute(review.projectRoot),
    candidate: file.status === "D" ? null : absolute(proposal.worktreeRoot) };
}

export function proposalNodes(review?: ProposalReview, recovery?: RecoveryList): ProposalNode[] {
  const retained: ProposalNode[] = (recovery?.items ?? []).map(item => ({ id: `recovery:${item.id}`, label: item.label,
    description: "Choose Resume for Review, Keep or Discard", recovery: { sessionId: recovery!.sessionId,
      modelRevision: recovery!.modelRevision, targetId: recovery!.targetId, recoveryId: item.id } }));
  if (!review) return retained.length ? retained : [{ id: "empty", label: "Run ICODA: Review Proposal to inspect the current candidate." }];
  const nodes: ProposalNode[] = [...retained, { id: "message", label: review.message },
    { id: "automatic", label: `Saved automatic approval: ${review.autoApprove ? "on" : "off"}`, description: "This review requires an explicit decision." }];
  const proposal = review.proposal;
  if (proposal) {
    nodes.push({ id: "summary", label: `Step ${proposal.number}: ${proposal.round}`, description: proposal.summary },
      { id: "delta", label: "Entity / API delta", description: proposal.delta || "Prose approach" },
      { id: "gate", label: proposal.canApprove ? "Ready for decision" : "Approval blocked", description: proposal.error || (proposal.evidenceFresh ? "" : "Rebuild candidate to refresh evidence.") });
    for (const [name, gate] of [["Build", proposal.build], ["Tests", proposal.tests]] as const) {
      if (gate) nodes.push({ id: name, label: `${name}: ${gate.ok === true ? "passed" : gate.ok === false ? "failed" : "not run"}` });
    }
    for (const file of proposal.files) nodes.push({ id: `file:${file.path}`, label: file.path, description: file.status,
      selection: { sessionId: review.sessionId, modelRevision: review.modelRevision, targetId: review.targetId,
        evidenceFingerprint: review.evidenceFingerprint, path: file.path } });
  }
  for (const [index, record] of review.records.entries()) nodes.push({ id: `history:${index}`, label: `Step ${record.number}: ${record.decision} — ${record.title}`,
    description: record.reason || record.rationale });
  return nodes;
}
