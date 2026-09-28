import { BackendError } from "./protocol";

const explanations: Record<string, string> = {
  project_not_open: "Open a workspace folder, then run ICODA: Open Project.",
  model_unavailable: "Run ICODA: Analyse Project to display its source structure.",
  source_missing: "The source file could not be found in this project.",
  missing_tool: "A required tool is unavailable. Run ICODA: Show Toolchain to inspect its configuration.",
  invalid_trace: "The trace could not be loaded. Choose a valid recording from this project.",
  trace_not_loaded: "Choose Load Trace to start recorded-call playback.",
  analysis_failed: "Project analysis failed. See ICODA Output for details.",
  cancelled: "Operation cancelled or superseded.",
  backend_exited: "The ICODA backend stopped. Run ICODA: Restart Backend to reconnect.",
  backend_disposed: "The ICODA backend is closed. Run ICODA: Restart Backend to reconnect.",
  stale_revision: "The project has changed. Refresh the view and try again.",
  stale_target: "The selected target has changed. Refresh the view and try again.",
  invalid_session: "The project session has changed. Run ICODA: Open Project again.",
};

/** Keep protocol codes in the error object; present its explanation at the UI boundary. */
export function viewError(error: unknown): string {
  if (!(error instanceof BackendError)) return error instanceof Error ? error.message : String(error);
  const detail = error.message.slice(`${error.code}: `.length).trim();
  const explanation = explanations[error.code];
  if (!detail || detail === error.code) return explanation ?? "ICODA could not complete this operation. See ICODA Output for details.";
  return explanation ? `${explanation} ${detail}` : detail;
}
