import { pathToFileURL } from "node:url";
import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError, ProjectModel, ResolvedSource, SessionContext, SourceReference } from "./protocol";
import { projectFile } from "./sourceChanges";
import { viewError } from "./viewErrors";
import { CandidateSource } from "./proposalData";
import { sameContext } from "./sessionState";

export type SourceOutcome =
  | { kind: "open"; uri: string; line: number; column: number }
  | { kind: "choose"; candidates: string[]; line: number }
  | { kind: "missing"; message: string }
  | { kind: "error"; code: string; message: string };

/** Convert the existing v1 success/error contract without reimplementing lookup ranking. */
export function sourceOutcome(root: string, response: ResolvedSource | BackendError): SourceOutcome {
  if (response instanceof BackendError) {
    if (response.code === "source_missing") return { kind: "missing", message: viewError(response) };
    const candidates = response.details.candidates;
    if (response.code === "source_ambiguous" && Array.isArray(candidates) && candidates.length > 1
        && candidates.every(file => typeof file === "string" && projectFile(root, file))) {
      return { kind: "choose", candidates, line: sourceLine(response.details.line) };
    }
    return { kind: "error", code: response.code, message: viewError(response) };
  }
  if (!projectFile(root, response.path)) {
    return { kind: "error", code: "source_missing", message: "Source is outside the selected project or in project metadata." };
  }
  return { kind: "open", uri: pathToFileURL(response.path).href, line: sourceLine(response.line), column: 1 };
}

function sourceLine(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : 1;
}

/** Every source request carries the current wire identity; obsolete replies produce no UI action. */
export async function resolveSource(client: Pick<BackendClient, "request">, session: ProjectSession,
  ref: SourceReference, candidate?: CandidateSource): Promise<SourceOutcome | undefined> {
  const ticket = session.identity.capture();
  const root = sourceRoot(session, ref, candidate);
  if (!ticket.context || !root) {
    return { kind: "error", code: "invalid_session", message: "This source belongs to a closed or different project." };
  }
  try {
    const result = await client.request<ResolvedSource>("source.resolve", ref, ticket.context);
    if (!session.identity.accept(ticket, result, "read")) return undefined;
    if (result.sourceRootId !== ref.sourceRootId) return undefined;
    return sourceOutcome(root, result);
  } catch (error) {
    if (!session.identity.isCurrent(ticket)) return undefined;
    if (!(error instanceof BackendError)) throw error;
    if (["source_missing", "source_ambiguous"].includes(error.code) && "sessionId" in error.details
        && !session.identity.accept(ticket, error.details as unknown as SessionContext, "read")) return undefined;
    return sourceOutcome(root, error);
  }
}

/** Candidate roots enter only through the checked proposal response, never a webview path. */
export function sourceRoot(session: ProjectSession, ref: SourceReference, candidate?: CandidateSource): string | undefined {
  if (ref.sourceRootId === session.sourceRootId) return session.data?.root;
  return candidate?.sourceRootId === ref.sourceRootId && sameContext(candidate, session.identity.context)
    ? candidate.root : undefined;
}

export interface EntityChoice {
  label: string;
  description: string;
  detail: string;
  ref: SourceReference;
}

const entityKinds = new Set(["class", "struct", "function", "method", "constructor", "destructor"]);

/** Use the held whole-project model, including files without callable entities. */
export function entityChoices(model: ProjectModel, root: string, sourceRootId: string): EntityChoice[] {
  const choices: EntityChoice[] = [];
  for (const { path } of model.files ?? []) {
    if (projectFile(root, path)) choices.push({
      label: path, description: "file", detail: path, ref: { sourceRootId, file: path },
    });
  }
  for (const entity of model.entities) {
    const { usr, kind, file, qualified_name, name, line } = entity;
    if (typeof usr !== "string" || typeof kind !== "string" || !entityKinds.has(kind)
        || typeof file !== "string" || !projectFile(root, file)) continue;
    choices.push({ label: String(qualified_name || name || usr), description: kind,
      detail: `${file}:${sourceLine(line)}`, ref: { sourceRootId, usr } });
  }
  return choices.sort((a, b) => a.label.localeCompare(b.label) || a.detail.localeCompare(b.detail));
}
