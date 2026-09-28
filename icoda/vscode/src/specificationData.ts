import { AnalysedProject, isObject, SessionContext } from "./protocol";

export interface Validation extends SessionContext {
  valid: boolean;
  findings: { id: string; severity: string; message: string }[];
}
export interface Specification extends Validation {
  document: Record<string, unknown>; schemaVersion: number; codeProfile: unknown; exists: boolean;
}
export interface SavedSpecification extends Specification, AnalysedProject {
  saved: true;
  postSaveError: { code: string; message: string; details: Record<string, unknown> } | null;
}
export interface Phase extends SessionContext {
  phase: string; allowedTransitions: string[]; transitions: { phase: string; reason: string }[];
}
export interface ProviderSelection { provider: string; model: string }
export interface ProviderChoice extends ProviderSelection { binary: string }
export interface ProviderInventory extends SessionContext {
  selection: ProviderSelection; emptyReason: string | null; message: string;
  providers: { id: string; label: string; installed: boolean; enabled: boolean; available: boolean;
    binary: string; binaryPath: string | null; loginHint: string; selectedModel: string;
    authenticationConfigured: boolean; models: { id: string; label: string; available: boolean }[] }[];
}
export interface SpecificationSnapshot {
  spec?: Specification; phase?: Phase; providers?: ProviderInventory; errors: string[];
}
export interface SpecificationNode { id: string; label: string; description?: string; children?: SpecificationNode[] }
export const specificationCommands = {
  open: "icoda.openSpecification", validate: "icoda.validateSpecification",
  phase: "icoda.advancePhase", provider: "icoda.selectProviderModel",
} as const;
export type SpecificationAction = keyof typeof specificationCommands;

/** Commands take no external arguments; all choices come from the current backend inventory. */
export function registerSpecificationCommands<T>(register: (name: string, action: (...args: unknown[]) => unknown) => T,
  execute: (action: SpecificationAction) => unknown): T[] {
  return Object.entries(specificationCommands).map(([action, name]) => register(name, (...args) =>
    args.length ? undefined : execute(action as SpecificationAction)));
}

export function providerSelection(value: unknown): ProviderSelection | undefined {
  if (!isObject(value) || Object.keys(value).sort().join(",") !== "model,provider") return undefined;
  return [value.provider, value.model].every(item => typeof item === "string" && item.length > 0
    && item.length <= 256 && !/[\x00-\x1f\x7f]/.test(item)) ? value as unknown as ProviderSelection : undefined;
}

/** Paths are resolved by Python. Native inputs cannot supply credentials or invocation arguments. */
export function providerChoice(value: unknown): ProviderChoice | undefined {
  if (!isObject(value) || Object.keys(value).sort().join(",") !== "binary,model,provider"
    || !providerSelection({ provider: value.provider, model: value.model })) return undefined;
  return [value.provider, value.model, value.binary].every(item => typeof item === "string" && item.trim() === item)
    && typeof value.binary === "string" && value.binary.length > 0 && value.binary.length <= 4096
    && !/[\x00-\x1f\x7f]/.test(value.binary) ? value as unknown as ProviderChoice : undefined;
}

export function specificationNodes(snapshot: SpecificationSnapshot, selection?: ProviderSelection): SpecificationNode[] {
  const { spec, phase, providers, errors } = snapshot;
  const nodes: SpecificationNode[] = errors.map((label, index) => ({ id: `error:${index}`, label }));
  if (phase) nodes.push({ id: "phase", label: `Phase: ${phase.phase}`, children: phase.transitions.map(item => ({
    id: `phase:${item.phase}`, label: item.phase, description: item.reason || "Available via Advance Phase",
  })) });
  if (spec) nodes.push(...specificationSections(spec));
  if (providers) nodes.push(providerNodes(providers, selection ?? providers.selection));
  return nodes;
}

function specificationSections(spec: Specification): SpecificationNode[] {
  const nodes: SpecificationNode[] = [];
  if (!spec.exists) nodes.push({ id: "missing", label: "No saved specification. Open Specification to edit the default." });
  const profile = Object.entries(isObject(spec.codeProfile) ? spec.codeProfile : {}).map(([key, value]) => ({ id: `profile:${key}`,
    label: key.replaceAll("_", " "), description: Array.isArray(value) ? value.join(", ") : String(value) }));
  nodes.push({ id: "profile", label: `Code Profile (schema ${spec.schemaVersion})`, children: profile.length ? profile : [
    { id: "profile:missing", label: "No Code Profile. Open Specification to add one." }] });
  nodes.push({ id: "validation", label: "Validation", children: spec.findings.length
    ? spec.findings.map(item => ({ id: item.id, label: item.message, description: item.severity }))
    : [{ id: "valid", label: spec.exists ? "Specification is valid." : "Default is valid; it has not been saved." }] });
  return nodes;
}

function providerNodes(inventory: ProviderInventory, selection: ProviderSelection): SpecificationNode {
  const children: SpecificationNode[] = inventory.providers.map(provider => ({ id: `provider:${provider.id}`,
    label: provider.label, description: !provider.installed ? "Not installed" : !provider.enabled ? "Disabled in ICODA" : "Available",
    children: [{ id: `binary:${provider.id}`, label: "Executable", description: provider.binaryPath ?? `Missing: ${provider.binary}` },
    { id: `selection:${provider.id}`, label: "Selected model", description: selection.provider === provider.id
      ? selection.model : provider.selectedModel },
    { id: `login:${provider.id}`, label: "CLI authentication", description: provider.loginHint || "Use the provider CLI's existing authentication." },
    { id: `auth:${provider.id}`, label: provider.authenticationConfigured
      ? "Authentication configuration detected (not verified)." : "Authentication not detected; CLI login or keychain may still be configured." },
    ...provider.models.map(model => ({ id: `model:${provider.id}:${model.id}`, label: model.label,
      description: selection.provider === provider.id && selection.model === model.id ? "Selected"
        : model.available ? model.id : "Unavailable" }))] }));
  if (inventory.emptyReason) children.unshift({ id: inventory.emptyReason, label: inventory.message });
  return { id: "providers", label: "Providers / Models", children };
}
