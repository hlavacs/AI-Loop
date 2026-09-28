import { graphInteractionControls } from "./graphInteractions";
/** Only nonce-protected local resources enter HTML; graph labels arrive as data. */
export function fileViewHtml(nonce: string, cspSource: string, script: string, style: string, interactions = script.replace(/[^/]+$/, "graphInteractions.js")): string {
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; style-src ${escape(cspSource)}; script-src 'nonce-${escape(nonce)}';">
<link rel="stylesheet" href="${escape(style)}"><title>ICODA File View</title></head>
<body>
<div id="toolbar" role="toolbar" aria-label="File View controls">
<button id="back" disabled>← Back</button><button id="breadcrumb" disabled aria-haspopup="menu">Whole Project</button>
<button id="reveal">Reveal active file</button>
${graphInteractionControls()}
<button id="zoomOut" aria-label="Zoom out">−</button><button id="fit">Fit</button>
<button id="zoomIn" aria-label="Zoom in">+</button></div>
<svg id="graph" tabindex="0" role="group" aria-label="File graph. Enter opens a cluster or file; arrows pan; plus and minus zoom; F fits.">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
<g id="scene"></g></svg>
<div id="clusterMenu" role="menu" aria-label="Cluster actions" hidden>
<button id="clusterPin" role="menuitem">Pin Cluster</button>
<button id="clusterRename" role="menuitem">Rename Cluster…</button>
<button id="fileAssign" role="menuitem" hidden>Assign File to Cluster…</button></div>
<p id="status" role="status" aria-live="polite">Loading File View…</p>
<script nonce="${escape(nonce)}" src="${escape(interactions)}"></script>
<script type="module" nonce="${escape(nonce)}" src="${escape(script)}"></script>
</body></html>`;
}

function escape(value: string): string {
  return value.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]!);
}
