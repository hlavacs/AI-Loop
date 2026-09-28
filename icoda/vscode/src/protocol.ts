/** Protocol v1 uses camelCase fields and top-level project identity. */
export const PROTOCOL_VERSION = 1;
export const MAX_REQUEST_BYTES = 1024 * 1024;

export interface SessionContext {
  sessionId: string;
  modelRevision: number;
  targetId: string | null;
}

export interface Initialization {
  protocolVersion: number;
  backendVersion: string;
  runtime: { python: string };
  capabilities: {
    methods: string[];
    cancellation: boolean;
    cancellableMethods?: string[];
    workflowKinds?: string[];
    purposeComments?: boolean;
    targetSelection: boolean;
    views: string[];
    maxMessageBytes: number;
  };
  analysisTimeoutSeconds: number;
}

/** Core model fields used by the tree and source picker. */
export interface ProjectModel {
  files?: { path: string }[];
  entities: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  stale: boolean;
  stale_reason: string;
}

export type SourceReference = { sourceRootId: string; line?: number }
  & ({ usr: string; file?: never } | { file: string; usr?: never });

export interface ResolvedSource extends SessionContext {
  sourceRootId: string;
  file: string;
  path: string;
  line: number;
}

export interface ProjectSnapshot extends SessionContext {
  sourceRootId: string;
  root: string;
  model: ProjectModel;
}

export interface OpenedProject extends ProjectSnapshot {
  cached: boolean;
  state: Record<string, unknown>;
  ui: Record<string, unknown>;
  layout: Record<string, unknown>;
}

export interface CreatedProject {
  root: string;
  writtenFiles: string[];
  specificationPath: string;
  state: Record<string, unknown>;
}

export interface Diagnostic {
  code?: string;
  file?: string;
  message: string;
}

export interface AnalysedProject extends ProjectSnapshot {
  diagnostics: Diagnostic[];
}

export interface Target {
  id: string | null;
  kind: "whole-project" | "executable" | "library";
  name: string;
  label: string;
  configuration: string | null;
  entryUsr: string | null;
}

export interface TargetList extends SessionContext {
  targets: Target[];
  diagnostics: Diagnostic[];
}

export interface TargetOperationResult extends TargetList {
  message: string;
  target: Target;
  executable: string | null;
  path: string | null;
  check?: { kind: "build" | "tests"; ok: true; output: string };
}

/** Full-project checks never turn an absent/malformed result into a passing gate. */
export function validateProjectCheck(value: unknown, kind: "build" | "tests"): void {
  const check = value as TargetOperationResult["check"];
  if (!check || typeof check !== "object" || Array.isArray(check)
    || Object.keys(check).sort().join(",") !== "kind,ok,output"
    || check.kind !== kind || check.ok !== true || typeof check.output !== "string") {
    throw new BackendError("invalid_response", "Invalid full-project check result.");
  }
}

export interface SelectedTarget extends SessionContext {
  model: ProjectModel;
}

export interface Notification {
  method: string;
  params: Record<string, unknown>;
}

/** Preserve typed failures, including details needed for recovery and revision updates. */
export class BackendError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(`${code}: ${message}`);
    this.name = "BackendError";
  }
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Responses are trusted only after checking their envelope, separately from notifications. */
export function readError(value: unknown): BackendError {
  if (!isObject(value) || typeof value.code !== "string"
      || typeof value.message !== "string" || !isObject(value.details)) {
    throw new Error("Invalid backend error envelope.");
  }
  return new BackendError(value.code, value.message, value.details);
}
